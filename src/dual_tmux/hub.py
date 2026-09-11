from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import log as ev
from . import statusbar, ui
from . import tmux as tmux_ops
from .activity import activity_path
from .config import AppConfig, load_config
from .identity import remote_dt_root
from .paths import entries_dir, home_dir, tunnels_dir
from .sshutil import SshTarget


def _ssh_control_path() -> Path:
    root = home_dir() / "ssh"
    candidate = root / "control-%C"
    if len(os.fsencode(candidate)) >= 96:
        digest = hashlib.sha256(os.fsencode(home_dir())).hexdigest()[:12]
        root = Path("/tmp") / f"dual-tmux-ssh-{os.getuid()}"
        candidate = root / f"{digest}-%C"
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return candidate


def ssh_argv(cfg: AppConfig | None = None, *, connect_timeout: int = 8) -> list[str]:
    cfg = cfg or load_config()
    target = SshTarget(cfg.server, cfg.ssh_port)
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "ControlMaster=auto",
        "-o",
        "ControlPersist=30",
        "-o",
        f"ControlPath={_ssh_control_path()}",
        *target.extra_args,
        target.dest,
    ]


def rsync_ssh(cfg: AppConfig | None = None) -> str:
    cfg = cfg or load_config()
    target = SshTarget(cfg.server, cfg.ssh_port)
    extra = " ".join(target.extra_args)
    control = shlex.quote(str(_ssh_control_path()))
    return (
        "ssh -o BatchMode=yes -o ConnectTimeout=8 "
        f"-o ControlMaster=auto -o ControlPersist=30 -o ControlPath={control} {extra}"
    ).rstrip()


def remote_root(cfg: AppConfig | None = None) -> str:
    cfg = cfg or load_config()
    return remote_dt_root(cfg.user)


LOCK_TTL = 300
# Four seconds leaves the claimant enough of the ten-second UX budget to fence
# the service-side writer and restore an input-ready Trigger.  The daemon
# renews every second, so a healthy owner gets multiple opportunities.
FAULT_TAKEOVER_TTL = 30
STALLED_OWNER_EVIDENCE_TTL = 300


def enabled(cfg: AppConfig | None = None) -> bool:
    return (cfg or load_config()).hub_enabled


def _require_hub(cfg: AppConfig) -> None:
    if not cfg.hub_enabled:
        raise SystemExit(
            "[err] no Hub configured; attach one with: "
            "dt config --server <ssh-host> --user <name>"
        )


def _run(
    argv: list[str],
    input: str | None = None,
    timeout: float | None = None,
    *,
    inherit_stdout: bool = False,
) -> subprocess.CompletedProcess:
    kwargs: dict = {
        "args": argv,
        "text": True,
        "input": input,
        "timeout": timeout,
    }
    if inherit_stdout:
        kwargs["stderr"] = subprocess.PIPE
    else:
        kwargs["capture_output"] = True
    return subprocess.run(check=False, **kwargs)


def _ensure_remote(cfg: AppConfig) -> None:
    _require_hub(cfg)
    dest = ssh_argv(cfg) + [
        (
            f"mkdir -p {remote_root(cfg)}/tunnels {remote_root(cfg)}/entries "
            f"{remote_root(cfg)}/locks {remote_root(cfg)}/activity "
            f"{remote_root(cfg)}/ownership {remote_root(cfg)}/occupancy"
        )
    ]
    result = _run(dest)
    if result.returncode != 0:
        err = (
            (result.stderr or result.stdout or "ssh mkdir failed").strip().splitlines()
        )
        raise SystemExit(f"[err] hub mkdir: {err[-1] if err else 'failed'}")


_RSYNC_PROGRESS_ARGS: list[str] | None = None


def _rsync_progress_args() -> list[str]:
    """Prefer overall progress, but macOS openrsync only has --progress."""
    global _RSYNC_PROGRESS_ARGS
    if _RSYNC_PROGRESS_ARGS is None:
        try:
            probe = subprocess.run(
                ["rsync", "--info=help"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            _RSYNC_PROGRESS_ARGS = ["--progress"]
        else:
            _RSYNC_PROGRESS_ARGS = (
                ["--info=progress2"] if probe.returncode == 0 else ["--progress"]
            )
    return list(_RSYNC_PROGRESS_ARGS)


def _progress_flag_unsupported(stderr: str) -> bool:
    text = (stderr or "").lower()
    return "unknown option" in text or "unrecognized option" in text


def _rsync_fail_message(stderr: str, stdout: str = "") -> str:
    lines = [
        line.strip()
        for line in ((stderr or "") + chr(10) + (stdout or "")).splitlines()
        if line.strip()
    ]
    for line in lines:
        low = line.lower()
        if "unrecognized option" in low or "unknown option" in low:
            return line
        if low.startswith("rsync error:"):
            return line
        if low.startswith("rsync:") and "usage:" not in low:
            return line
    return lines[0] if lines else "failed"


def _rsync(
    src: str,
    dest: str,
    cfg: AppConfig,
    *,
    update: bool = False,
    preserve_ownership: bool = True,
    progress: bool = False,
) -> None:
    argv = ["rsync", "-a"]
    if not preserve_ownership:
        argv.extend(["--no-owner", "--no-group"])
    if update:
        argv.append("--update")
    if progress:
        argv.extend(_rsync_progress_args())
    argv.extend(["-e", rsync_ssh(cfg), src, dest])
    result = _run(argv, inherit_stdout=progress)
    if progress and result.returncode != 0 and _progress_flag_unsupported(
        result.stderr or ""
    ):
        argv = [item for item in argv if item not in {"--info=progress2", "--progress"}]
        argv.insert(2, "--progress")
        result = _run(argv, inherit_stdout=True)
    if result.returncode != 0:
        raise SystemExit(
            f"[err] rsync: {_rsync_fail_message(result.stderr or '', result.stdout or '')}"
        )


def push(cfg: AppConfig | None = None) -> str:
    cfg = cfg or load_config()
    _require_hub(cfg)
    root = remote_root(cfg)
    _ensure_remote(cfg)
    tunnels_dir().mkdir(parents=True, exist_ok=True)
    entries_dir().mkdir(parents=True, exist_ok=True)
    host = SshTarget(cfg.server, cfg.ssh_port).dest
    _rsync(f"{tunnels_dir()}/", f"{host}:{root}/tunnels/", cfg)
    _rsync(f"{entries_dir()}/", f"{host}:{root}/entries/", cfg)
    log = activity_path()
    if log.is_file():
        _rsync(str(log), f"{host}:{root}/activity/{cfg.client}.log", cfg)
    ev.emit("hub.push", host=host, root=root)
    return f"{host}:{root}"


def pull(
    cfg: AppConfig | None = None,
    *,
    name: str = "",
    run: str = "",
    progress: bool = False,
) -> str:
    from .store import normalize_dt

    cfg = cfg or load_config()
    _require_hub(cfg)
    root = remote_root(cfg)
    tunnels_dir().mkdir(parents=True, exist_ok=True)
    entries_dir().mkdir(parents=True, exist_ok=True)
    host = SshTarget(cfg.server, cfg.ssh_port).dest
    if name:
        normalized = normalize_dt(name)
        if "/" in normalized or normalized in {"dt-.", "dt-.."}:
            raise SystemExit(f"[err] invalid tunnel name: {name}")
        target_tunnel = tunnels_dir() / f"{normalized}.json"
        _rsync(
            f"{host}:{root}/tunnels/{normalized}.json",
            str(target_tunnel),
            cfg,
            progress=progress,
        )
        if not run and target_tunnel.is_file():
            try:
                t_data = json.loads(target_tunnel.read_text(encoding="utf-8"))
                run = str(t_data.get("run") or "")
            except Exception:
                pass
        if run and "/" not in run and not run.startswith("."):
            _rsync(
                f"{host}:{root}/entries/{run}.cmd",
                f"{entries_dir()}/{run}.cmd",
                cfg,
                progress=progress,
            )
        ev.emit("hub.pull", host=host, root=root, name=normalized)
    else:
        _rsync(f"{host}:{root}/tunnels/", f"{tunnels_dir()}/", cfg, progress=progress)
        _rsync(f"{host}:{root}/entries/", f"{entries_dir()}/", cfg, progress=progress)
        ev.emit("hub.pull", host=host, root=root)
    return f"{host}:{root}"


def read_tunnel_binding(name: str, cfg: AppConfig | None = None) -> dict:
    """Read one owner-committed binding without merging local timestamps."""
    from .store import normalize_dt

    cfg = cfg or load_config()
    _require_hub(cfg)
    normalized = normalize_dt(name)
    if normalized != name or "/" in normalized or normalized in {"dt-.", "dt-.."}:
        raise SystemExit(f"[err] invalid tunnel name: {name}")
    root = remote_root(cfg)
    host = SshTarget(cfg.server, cfg.ssh_port).dest
    with tempfile.TemporaryDirectory(prefix="dual-tmux-binding-") as raw:
        dest = Path(raw) / f"{normalized}.json"
        _rsync(f"{host}:{root}/tunnels/{normalized}.json", str(dest), cfg)
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(
                f"[err] invalid owner-committed binding for {normalized}"
            ) from exc
    if data.get("name") != normalized:
        raise SystemExit(f"[err] owner-committed binding identity mismatch: {normalized}")
    return data


def _tunnel_time(path: Path) -> float:
    """Use the binding's logical clock, falling back to its file mtime."""
    try:
        value = str(
            json.loads(path.read_text(encoding="utf-8")).get("updated_at") or ""
        )
        if value:
            return datetime.fromisoformat(value).timestamp()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _copy_newer(left: Path, right: Path, *, logical_time: bool = False) -> Path:
    """Make two files converge and return the selected source path."""
    if not left.is_file() and not right.is_file():
        return left
    left_mtime = left.stat().st_mtime_ns if left.is_file() else 0
    right_mtime = right.stat().st_mtime_ns if right.is_file() else 0
    if not left.is_file():
        winner, loser = right, left
    elif not right.is_file():
        winner, loser = left, right
    else:
        clock = _tunnel_time if logical_time else lambda path: path.stat().st_mtime
        try:
            left_bytes = left.read_bytes()
            right_bytes = right.read_bytes()
        except OSError:
            left_bytes = right_bytes = b""
        if left_bytes == right_bytes:
            return left
        left_key = (clock(left), hashlib.sha256(left_bytes).digest())
        right_key = (clock(right), hashlib.sha256(right_bytes).digest())
        winner, loser = (right, left) if right_key > left_key else (left, right)
    loser.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(winner, loser)
    merged_mtime = max(left_mtime, right_mtime) + 1_000_000_000
    os.utime(winner, ns=(merged_mtime, merged_mtime))
    os.utime(loser, ns=(merged_mtime, merged_mtime))
    return winner


def _copy_preferred(preferred: Path, other: Path) -> None:
    if preferred.is_file():
        merged_mtime = (
            max(
                preferred.stat().st_mtime_ns,
                other.stat().st_mtime_ns if other.is_file() else 0,
            )
            + 1_000_000_000
        )
        other.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(preferred, other)
        os.utime(preferred, ns=(merged_mtime, merged_mtime))
        os.utime(other, ns=(merged_mtime, merged_mtime))
    elif other.is_file():
        preferred.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(other, preferred)


def merge_snapshot(
    local_tunnels: Path,
    local_entries: Path,
    hub_tunnels: Path,
    hub_entries: Path,
) -> None:
    """Merge a downloaded hub snapshot with local bindings without deletions."""
    for root in (local_tunnels, local_entries, hub_tunnels, hub_entries):
        root.mkdir(parents=True, exist_ok=True)
    names = {
        path.name
        for root in (local_tunnels, hub_tunnels)
        for path in root.glob("dt-*.json")
    }
    owned_entries: set[str] = set()
    for name in sorted(names):
        local = local_tunnels / name
        remote = hub_tunnels / name
        winner = _copy_newer(local, remote, logical_time=True)
        try:
            run = str(json.loads(winner.read_text(encoding="utf-8")).get("run") or "")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            run = ""
        if run:
            entry = f"{run}.cmd"
            owned_entries.add(entry)
            local_entry = local_entries / entry
            hub_entry = hub_entries / entry
            if winner.parent == local_tunnels:
                _copy_preferred(local_entry, hub_entry)
            else:
                _copy_preferred(hub_entry, local_entry)
    orphan_entries = {
        path.name
        for root in (local_entries, hub_entries)
        for path in root.glob("run_*.cmd")
    } - owned_entries
    for name in sorted(orphan_entries):
        _copy_newer(local_entries / name, hub_entries / name)


def sync(cfg: AppConfig | None = None) -> str:
    """Merge local and hub bindings, then publish the merged snapshot."""
    cfg = cfg or load_config()
    _require_hub(cfg)
    root = remote_root(cfg)
    host = SshTarget(cfg.server, cfg.ssh_port).dest
    _ensure_remote(cfg)
    tunnels_dir().mkdir(parents=True, exist_ok=True)
    entries_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dual-tmux-sync-") as raw:
        snapshot = Path(raw)
        hub_tunnels = snapshot / "tunnels"
        hub_entries = snapshot / "entries"
        hub_tunnels.mkdir()
        hub_entries.mkdir()
        _rsync(f"{host}:{root}/tunnels/", f"{hub_tunnels}/", cfg)
        _rsync(f"{host}:{root}/entries/", f"{hub_entries}/", cfg)
        merge_snapshot(tunnels_dir(), entries_dir(), hub_tunnels, hub_entries)
        _rsync(f"{hub_tunnels}/", f"{host}:{root}/tunnels/", cfg, update=True)
        _rsync(f"{hub_entries}/", f"{host}:{root}/entries/", cfg, update=True)
    log = activity_path()
    if log.is_file():
        _rsync(str(log), f"{host}:{root}/activity/{cfg.client}.log", cfg)
    ev.emit("hub.sync", host=host, root=root)
    return f"{host}:{root}"


def remove_remote(name: str, run: str = "", cfg: AppConfig | None = None) -> None:
    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        return
    root = remote_root(cfg)
    parts = [
        (
            f"rm -f {root}/tunnels/{name}.json {root}/locks/{name} "
            f"{root}/ownership/{name}.json"
        )
    ]
    if run:
        parts.append(f"rm -f {root}/entries/{run}.cmd")
    result = _run(ssh_argv(cfg) + ["; ".join(parts)])
    if result.returncode != 0:
        raise SystemExit("[err] hub rm failed")


def _lock_remote(
    action: str,
    name: str,
    force: bool = False,
    cfg: AppConfig | None = None,
    ttl: int = LOCK_TTL,
    owner: str = "",
    expected_generation: int = 0,
) -> tuple[str, str, int, int]:
    cfg = cfg or load_config()
    instance = existing_instance_id() if action == "read" else instance_id()
    evidence = {}
    if action == "claim":
        try:
            from .activity import read_evidence

            evidence = read_evidence(name)
        except (OSError, ValueError):
            evidence = {}
    encoded_evidence = base64.b64encode(
        json.dumps(evidence, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    script = r"""
set -e
ROOT="$1"; NAME="$2"; ME="$3"; TTL="$4"; ACTION="$5"; FORCE="$6"; INSTANCE="$7"; EVIDENCE="$8"; EXPECTED="$9"; LEGACY_TTL="${10}"
mkdir -p "$ROOT/locks" "$ROOT/ownership"
f="$ROOT/locks/$NAME"
side="$ROOT/ownership/$NAME.json"
now=$(date +%s)
holder=""; age=99999; generation=0
side_present=0; side_instance=""; side_generation=0; side_protocol=1; side_takeover=""
exec 9>>"$f"
if ! flock -n 9; then
  value=$(cat "$f" 2>/dev/null || true)
  holder=$(printf '%s' "$value" | cut -d@ -f1)
  generation=$(printf '%s' "$value" | cut -d@ -f3)
  echo "HELD ${holder:-active-daemon} 0 ${generation:-0}"
  exit 2
fi
if [ -f "$f" ]; then
  holder=$(cut -d@ -f1 "$f")
  ts=$(cut -d@ -f2 "$f")
  generation=$(cut -d@ -f3 "$f")
  ts=${ts:-0}
  generation=${generation:-0}
  age=$((now - ts))
fi
if [ -s "$side" ]; then
  values=$(python3 - "$side" <<'PY'
import json,sys
try:
 with open(sys.argv[1]) as f: x=json.load(f)
 takeover=x.get('takeover') if isinstance(x.get('takeover'),dict) else {}
 print('1|'+str(x.get('instance_id') or '')+'|'+str(int(x.get('generation') or 0))+'|'+str(int(x.get('lease_protocol') or 1))+'|'+str(takeover.get('status') or ''))
except Exception: print('0||0|1|')
PY
)
  side_present=$(printf '%s' "$values" | cut -d'|' -f1)
  side_instance=$(printf '%s' "$values" | cut -d'|' -f2)
  side_generation=$(printf '%s' "$values" | cut -d'|' -f3)
  side_protocol=$(printf '%s' "$values" | cut -d'|' -f4)
  side_takeover=$(printf '%s' "$values" | cut -d'|' -f5)
fi
if [ "$ACTION" = "read" ]; then
  if [ -n "$holder" ] && [ "$age" -le "$TTL" ]; then echo "HELD $holder $age ${generation:-0}"; else echo "FREE"; fi
  exit 0
fi
if [ "$ACTION" = "release" ]; then
  if [ "$holder" = "$ME" ] && { [ "$EXPECTED" = "0" ] || { [ "$generation" = "$EXPECTED" ] && { [ -z "$side_instance" ] || [ "$side_instance" = "$INSTANCE" ]; }; }; }; then
    : > "$f"
    python3 - "$side" "$NAME" "$generation" "$now" <<'PY'
import json,os,sys,tempfile
path,name,generation,now=sys.argv[1:]
value={"schema":2,"name":name,"holder":"","instance_id":"","generation":int(generation or 0),"renewed_at":int(now),"expires_at":int(now),"evidence":{},"handoff":None}
os.makedirs(os.path.dirname(path),exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.ownership-',dir=os.path.dirname(path))
with os.fdopen(fd,'w') as f: json.dump(value,f,separators=(',',':')); f.write('\n')
os.replace(tmp,path)
PY
    echo "FREE"
  else echo "HELD ${holder:-—} $age ${generation:-0}"; fi
  exit 0
fi
if [ "$ACTION" = "renew" ]; then
  # Lease v2 may be renewed after its four-second deadline only by the exact
  # same Client installation and generation. This is safe because renewal and
  # fault-takeover reservation use the same Hub flock: if a claimant has
  # reserved the expired generation, side_takeover=fencing rejects renewal;
  # if renewal wins first, the claimant observes an active lease. A delayed
  # SSH round trip therefore no longer destroys a healthy local session.
  renew_allowed=0
  if [ "$side_protocol" = "2" ]; then
    if [ "$holder" = "$ME" ] && [ "$generation" = "$EXPECTED" ] && [ "$side_present" = "1" ] && [ "$side_generation" = "$generation" ] && [ "$side_instance" = "$INSTANCE" ] && [ "$side_takeover" != "fencing" ]; then renew_allowed=1; fi
  elif [ "$holder" = "$ME" ] && [ "$age" -le "$LEGACY_TTL" ] && [ "$generation" = "$EXPECTED" ] && { [ "$side_present" = "0" ] || [ "$side_generation" = "$generation" ]; } && { [ -z "$side_instance" ] || [ "$side_instance" = "$INSTANCE" ]; } && [ "$side_takeover" != "fencing" ]; then
    renew_allowed=1
  fi
  if [ "$renew_allowed" = "1" ]; then
    echo "$ME@$now@${generation:-1}" > "$f"
    python3 - "$side" "$NAME" "$ME" "$INSTANCE" "$generation" "$now" "$TTL" <<'PY'
import json,os,sys,tempfile
path,name,holder,instance,generation,now,ttl=sys.argv[1:]
try:
 with open(path) as f: value=json.load(f)
except Exception: value={"schema":2,"name":name,"holder":holder,"instance_id":instance,"generation":int(generation or 0),"evidence":{},"handoff":None}
value['holder']=holder; value['instance_id']=instance; value['generation']=int(generation or 0)
value['lease_protocol']=2; value['lease_ttl']=int(ttl)
value['renewed_at']=int(now); value['expires_at']=int(now)+int(ttl)
fd,tmp=tempfile.mkstemp(prefix='.ownership-',dir=os.path.dirname(path))
with os.fdopen(fd,'w') as f: json.dump(value,f,separators=(',',':')); f.write('\n')
os.replace(tmp,path)
PY
    echo "OK $ME 0 ${generation:-1}"
  else
    echo "HELD ${holder:-—} $age ${generation:-0}"
  fi
  exit 0
fi
if [ "$ACTION" = "claim" ] && [ "$side_takeover" = "fencing" ]; then
  echo "HELD ${holder:-takeover-pending} $age ${generation:-0}"
  exit 2
fi
if [ "$ACTION" = "claim" ] && [ "$holder" = "$ME" ] && [ "$age" -le "$TTL" ] && [ -n "$side_instance" ] && [ "$side_generation" = "$generation" ] && [ "$side_instance" != "$INSTANCE" ] && [ "$FORCE" != "1" ]; then
  echo "HELD $holder $age ${generation:-0}"
  exit 2
fi
if [ "$ACTION" = "claim" ] && [ -z "$holder" ] && [ "$side_generation" -gt "$generation" ]; then
  generation="$side_generation"
fi
if [ -n "$holder" ] && [ "$holder" != "$ME" ] && [ "$age" -le "$TTL" ] && [ "$FORCE" != "1" ]; then
  echo "HELD $holder $age ${generation:-0}"
  exit 2
fi
if [ "$holder" != "$ME" ] || { [ -n "$side_instance" ] && [ "$side_generation" = "$generation" ] && [ "$side_instance" != "$INSTANCE" ]; }; then generation=$((${generation:-0} + 1)); fi
echo "$ME@$now@${generation:-1}" > "$f"
python3 - "$side" "$NAME" "$ME" "$INSTANCE" "${generation:-1}" "$now" "$TTL" "$EVIDENCE" <<'PY'
import base64,json,os,sys,tempfile
path,name,holder,instance,generation,now,ttl,evidence=sys.argv[1:]
try: ev=json.loads(base64.b64decode(evidence).decode()) if evidence else {}
except Exception: ev={}
old={}
try:
 with open(path) as f: old=json.load(f)
except Exception: pass
handoff=old.get('handoff') if old.get('holder')==holder and int(old.get('generation') or 0)==int(generation) else None
value={"schema":2,"lease_protocol":2,"lease_ttl":int(ttl),"name":name,"holder":holder,"instance_id":instance,"generation":int(generation),"renewed_at":int(now),"expires_at":int(now)+int(ttl),"evidence":ev,"handoff":handoff}
os.makedirs(os.path.dirname(path),exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.ownership-',dir=os.path.dirname(path))
with os.fdopen(fd,'w') as f: json.dump(value,f,separators=(',',':')); f.write('\n')
os.replace(tmp,path)
PY
echo "OK $ME 0 ${generation:-1}"
"""
    try:
        result = _run(
            ssh_argv(cfg, connect_timeout=2)
            + [
                "bash",
                "-s",
                "--",
                remote_root(cfg),
                name,
                owner or cfg.client,
                str(ttl),
                action,
                "1" if force else "0",
                instance,
                encoded_evidence,
                str(int(expected_generation or 0)),
                str(LOCK_TTL),
            ],
            input=script,
            timeout=8,
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            "[err] hub lock timed out after 8s; ownership was not changed"
        ) from exc
    line = (result.stdout or "").strip().splitlines()
    text = line[-1] if line else ""
    parts = text.split()
    kind = parts[0] if parts else "ERR"
    holder = parts[1] if len(parts) > 1 else ""
    age = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    generation = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    if result.returncode not in (0, 2) and kind not in {"OK", "HELD", "FREE"}:
        err = (result.stderr or text or "lock failed").strip().splitlines()
        raise SystemExit(f"[err] hub lock: {err[-1] if err else 'failed'}")
    return kind, holder, age, generation


def instance_id() -> str:
    """Stable identity for this installation, distinct from the Client name."""
    from .paths import home_dir

    path = home_dir() / "instance-id"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    value = f"{os.uname().nodename}:{uuid.uuid4().hex}"
    try:
        fd, raw = tempfile.mkstemp(prefix=".instance-", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
        os.chmod(raw, 0o600)
        os.replace(raw, path)
    except OSError:
        return value
    return value


def existing_instance_id() -> str:
    from .paths import home_dir

    try:
        return (home_dir() / "instance-id").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_lock(name: str) -> tuple[str, int]:
    """Return occupancy holder and age. Empty when Hub is off or unread."""
    from .occupancy import read_occupancy

    if not enabled():
        return "", 0
    try:
        occ = read_occupancy(name)
    except SystemExit:
        return "", 0
    holder = str(occ.get("holder") or "")
    claimed = int(occ.get("claimed_at") or 0)
    age = max(0, int(time.time()) - claimed) if claimed else 0
    return (holder, age) if holder else ("", 0)


def release(name: str, *, generation: int = 0) -> None:
    """Drop this Client's occupancy. Foreign holders fail closed."""
    from .occupancy import release_occupancy

    if not enabled():
        return
    release_occupancy(name)
    ev.emit("hub.release", name=name)


FEISHU_LEASE_NAME = "__feishu_ws__"
FEISHU_LEASE_TTL = 15


def claim_feishu_lease(
    cfg: AppConfig | None = None, *, owner: str = ""
) -> tuple[bool, str, int]:
    """Renew the single-active Feishu connector lease without stealing it."""
    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        return True, owner or cfg.client, 1
    kind, holder, _age, generation = _lock_remote(
        "claim", FEISHU_LEASE_NAME, cfg=cfg, ttl=FEISHU_LEASE_TTL, owner=owner
    )
    return kind == "OK", holder, generation


def release_feishu_lease(cfg: AppConfig | None = None, *, owner: str = "") -> None:
    cfg = cfg or load_config()
    if cfg.hub_enabled:
        _lock_remote(
            "release", FEISHU_LEASE_NAME, cfg=cfg, ttl=FEISHU_LEASE_TTL, owner=owner
        )


def claim(name: str, force: bool = False) -> str:
    """Local helper. Service mode writes occupancy."""
    if not enabled():
        return load_config().client
    from .occupancy import claim_occupancy

    return str(claim_occupancy(name).get("holder") or load_config().client)


def drop_local(data: dict) -> list[str]:

    dropped = []
    for key in ("op", "run"):
        name = data.get(key) or ""
        if name and tmux_ops.drop_session(name):
            dropped.append(name)
    if dropped:
        ev.emit("dt.drop", name=data.get("name"), sessions=",".join(dropped))
        ui.info(f"dropped tmux  {' '.join(dropped)}")
    return dropped


def park_local(data: dict) -> list[str]:
    return drop_local(data)


def require_active(data: dict, force: bool = False) -> dict:
    """Declare occupancy for this Client. Last writer wins; no lease TTL."""
    from .occupancy import claim_occupancy

    name = str(data["name"])
    if not enabled():
        return {
            "generation": int(data.get("ownership_generation") or 0),
            "holder": load_config().client,
        }
    claimed = claim_occupancy(name)
    generation = int(claimed.get("generation") or 0)
    if generation and generation != int(data.get("ownership_generation") or 0):
        from .store import find_dt, now_iso, save

        data["ownership_generation"] = generation
        data["updated_at"] = now_iso()
        save(find_dt(name), data)
    return {
        "generation": generation,
        "holder": str(claimed.get("holder") or load_config().client),
    }


def enforce_local() -> None:
    from .occupancy import foreign_holder, read_occupancy
    from .store import iter_dt_files, load

    cfg = load_config()
    if not cfg.hub_enabled:
        return
    me = cfg.client
    for path in iter_dt_files():
        data = load(path)
        name = data.get("name") or path.stem
        try:
            occ = read_occupancy(name, cfg)
        except SystemExit:
            continue
        if foreign_holder(occ, me):
            drop_local(data)


def push_best_effort(wait: bool = False) -> None:
    if not enabled():
        return

    def _run_push() -> None:
        try:
            dest = push()
            statusbar.write_state(True, dest)
            ev.emit("hub.push.ok", dest=dest)
        except SystemExit as exc:
            statusbar.write_state(False, str(exc))
            ev.emit("hub.push.fail", error=str(exc))

    if wait:
        try:
            dest = push()
            statusbar.write_state(True, dest)
            ui.info(f"hub push  {dest}")
        except SystemExit as exc:
            statusbar.write_state(False, str(exc))
            ui.warn(f"hub push skipped  {exc}")
        return
    threading.Thread(target=_run_push, daemon=True).start()


def sync_best_effort(wait: bool = False) -> None:
    if not enabled():
        return

    def _run_sync() -> None:
        try:
            dest = sync()
            statusbar.write_state(True, dest)
            ev.emit("hub.sync.ok", dest=dest)
        except SystemExit as exc:
            statusbar.write_state(False, str(exc))
            ev.emit("hub.sync.fail", error=str(exc))

    if wait:
        try:
            dest = sync()
            statusbar.write_state(True, dest)
            ui.info(f"hub sync  {dest}")
        except SystemExit as exc:
            statusbar.write_state(False, str(exc))
            ui.warn(f"hub sync skipped  {exc}")
        return
    threading.Thread(target=_run_sync, daemon=True).start()
