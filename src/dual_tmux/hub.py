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
from .activity import TICKS, activity_path, frozen_last_ticks
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
OWNERSHIP_LEASE_TTL = 4
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
    argv: list[str], input: str | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        input=input,
        timeout=timeout,
        check=False,
    )


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


def _rsync(
    src: str,
    dest: str,
    cfg: AppConfig,
    *,
    update: bool = False,
    preserve_ownership: bool = True,
) -> None:
    argv = ["rsync", "-a"]
    if not preserve_ownership:
        argv.extend(["--no-owner", "--no-group"])
    if update:
        argv.append("--update")
    argv.extend(["-e", rsync_ssh(cfg), src, dest])
    result = _run(argv)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "rsync failed").strip().splitlines()
        raise SystemExit(f"[err] rsync: {err[-1] if err else 'failed'}")


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


def pull(cfg: AppConfig | None = None) -> str:
    cfg = cfg or load_config()
    _require_hub(cfg)
    root = remote_root(cfg)
    tunnels_dir().mkdir(parents=True, exist_ok=True)
    entries_dir().mkdir(parents=True, exist_ok=True)
    host = SshTarget(cfg.server, cfg.ssh_port).dest
    _rsync(f"{host}:{root}/tunnels/", f"{tunnels_dir()}/", cfg)
    _rsync(f"{host}:{root}/entries/", f"{entries_dir()}/", cfg)
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
    if not enabled():
        return "", 0
    kind, holder, age, _generation = _lock_remote("read", name)
    if kind == "HELD":
        return holder, age
    return "", 0


def read_ownership(name: str, cfg: AppConfig | None = None) -> dict:
    """Read Lease v2 while treating the legacy lock as the authority."""
    cfg = cfg or load_config()
    now = int(time.time())
    if not cfg.hub_enabled:
        return {
            "schema": 2,
            "name": name,
            "state": "owned",
            "holder": cfg.client,
            "instance_id": existing_instance_id(),
            "generation": 1,
            "renewed_at": now,
            "expires_at": 0,
            "age_seconds": 0,
            "evidence": {},
            "handoff": None,
            "source": "local",
            "conflict": False,
        }
    script = r"""
set -e
ROOT="$1"; NAME="$2"
lock="$ROOT/locks/$NAME"; side="$ROOT/ownership/$NAME.json"
if [ -e "$lock" ]; then exec 9<"$lock"; flock -s 9; fi
printf 'V1 '; if [ -e "$lock" ]; then base64 <"$lock" | tr -d '\n'; fi; printf '\n'
printf 'V2 '; if [ -e "$side" ]; then base64 <"$side" | tr -d '\n'; fi; printf '\n'
"""
    result = _run(
        ssh_argv(cfg, connect_timeout=2) + ["bash", "-s", "--", remote_root(cfg), name],
        input=script,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ownership read failed").strip()
        raise SystemExit(f"[err] hub ownership: {detail.splitlines()[-1]}")
    values: dict[str, bytes] = {}
    for line in (result.stdout or "").splitlines():
        key, _, value = line.partition(" ")
        if key in {"V1", "V2"}:
            try:
                values[key] = base64.b64decode(value)
            except ValueError:
                values[key] = b""
    raw = values.get("V1", b"").decode("utf-8", "replace").strip()
    parts = raw.split("@") if raw else []
    holder = parts[0] if parts else ""
    stamp = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    generation = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    age = max(0, now - stamp) if stamp else 0
    try:
        sidecar = json.loads(values.get("V2", b"") or b"{}")
    except (json.JSONDecodeError, TypeError):
        sidecar = {}
    takeover = (
        sidecar.get("takeover") if isinstance(sidecar.get("takeover"), dict) else {}
    )
    # finish_fault_takeover commits the sidecar before the legacy lock.  If
    # the SSH process dies between those two atomic writes, any Client may
    # finish publishing that already-committed decision; it cannot choose a
    # different holder or generation.
    if (
        takeover.get("status") == "committed"
        and takeover.get("previous_holder") == holder
        and sidecar.get("holder") == takeover.get("claimant")
        and int(sidecar.get("generation") or 0) == generation + 1
    ):
        repaired = _fault_takeover_remote(
            name,
            "repair",
            request_id=str(takeover.get("request_id") or ""),
            generation=generation,
            cfg=cfg,
        )
        if repaired.get("ok"):
            return read_ownership(name, cfg)
    aligned = bool(
        sidecar
        and sidecar.get("holder") == holder
        and int(sidecar.get("generation") or 0) == generation
    )
    lease_ttl = (
        int(sidecar.get("lease_ttl") or OWNERSHIP_LEASE_TTL)
        if aligned and sidecar.get("lease_protocol") == 2
        else LOCK_TTL
    )
    active = bool(
        holder
        and stamp
        and (age < lease_ttl if lease_ttl != LOCK_TTL else age <= lease_ttl)
    )
    side_instance = str(sidecar.get("instance_id") or "") if aligned else ""
    local_instance = existing_instance_id()
    mine = bool(
        holder == cfg.client
        and (not aligned or not side_instance or side_instance == local_instance)
    )
    return {
        "schema": 2,
        "name": name,
        "state": "owned"
        if active and mine
        else ("foreign" if active else ("expired" if holder else "free")),
        "holder": holder if active else "",
        "instance_id": side_instance,
        "generation": generation,
        "renewed_at": stamp,
        "expires_at": stamp + lease_ttl if stamp else 0,
        "lease_protocol": int(sidecar.get("lease_protocol") or 1) if aligned else 1,
        "lease_ttl": lease_ttl,
        "age_seconds": age,
        "evidence": sidecar.get("evidence")
        if aligned and isinstance(sidecar.get("evidence"), dict)
        else {},
        "handoff": sidecar.get("handoff")
        if aligned and isinstance(sidecar.get("handoff"), dict)
        else None,
        "takeover": sidecar.get("takeover")
        if aligned and isinstance(sidecar.get("takeover"), dict)
        else None,
        "source": "v2" if aligned else "v1",
        "conflict": bool(sidecar and not aligned),
    }


def _handoff_remote(
    name: str,
    action: str,
    *,
    request_id: str,
    generation: int,
    reason: str = "",
    timeout: int = 0,
    cfg: AppConfig | None = None,
) -> dict:
    cfg = cfg or load_config()
    # OpenSSH joins argv into a remote shell command; an empty positional
    # argument would collapse and shift TIMEOUT into REASON.
    payload = base64.b64encode(reason.encode("utf-8")).decode("ascii") or "-"
    script = r"""
set -e
ROOT="$1"; NAME="$2"; ACTION="$3"; REQUEST="$4"; CLAIMANT="$5"; INSTANCE="$6"; GENERATION="$7"; REASON="$8"; TIMEOUT="$9"; LEASE_TTL="${10}"
lock="$ROOT/locks/$NAME"; side="$ROOT/ownership/$NAME.json"
mkdir -p "$ROOT/locks" "$ROOT/ownership"; exec 9>>"$lock"; flock -x 9
python3 - "$lock" "$side" "$NAME" "$ACTION" "$REQUEST" "$CLAIMANT" "$INSTANCE" "$GENERATION" "$REASON" "$TIMEOUT" "$LEASE_TTL" <<'PY'
import base64,json,os,sys,tempfile,time
lock,path,name,action,request,claimant,instance,generation,reason,timeout,lease_ttl=sys.argv[1:]
parts=open(lock).read().strip().split('@') if os.path.exists(lock) else []
holder=parts[0] if parts else ''; current=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 0
try:
 with open(path) as f: data=json.load(f)
except Exception: data={}
if current != int(generation) or data.get('holder') != holder or int(data.get('generation') or 0) != current:
 print(json.dumps({'ok':False,'code':'generation_conflict','generation':current})); raise SystemExit(3)
handoff=data.get('handoff') if isinstance(data.get('handoff'),dict) else None
takeover=data.get('takeover') if isinstance(data.get('takeover'),dict) else None
now=int(time.time())
ok=True; code=''
if takeover and takeover.get('status') == 'fencing':
 print(json.dumps({'ok':False,'code':'fault_takeover_in_progress','generation':current})); raise SystemExit(13)
if action=='request':
 if holder == claimant and (not data.get('instance_id') or data.get('instance_id') == instance):
  print(json.dumps({'ok':False,'code':'already_owner','generation':current})); raise SystemExit(12)
 if handoff and handoff.get('status') in ('pending','pending_v2','committing'):
  if handoff.get('claimant') == claimant and handoff.get('claimant_instance_id') == instance:
   print(json.dumps({'ok':True,'code':'idempotent','handoff':handoff,'generation':current})); raise SystemExit(0)
  print(json.dumps({'ok':False,'code':'handoff_pending','handoff':handoff})); raise SystemExit(4)
 detail=base64.b64decode(reason).decode('utf-8','replace') if reason != '-' else ''
 handoff={'protocol':2,'request_id':request,'status':'pending_v2','claimant':claimant,'claimant_instance_id':instance,'requested_at':now,'deadline_at':now+max(1,int(timeout or 1)),'reason':detail}
elif not handoff or handoff.get('request_id') != request:
 print(json.dumps({'ok':False,'code':'request_not_found'})); raise SystemExit(5)
elif action=='commit':
 if claimant != holder or (data.get('instance_id') and data.get('instance_id') != instance):
  print(json.dumps({'ok':False,'code':'not_owner'})); raise SystemExit(7)
 if handoff.get('status') != 'pending_v2':
  print(json.dumps({'ok':False,'code':'invalid_state','handoff':handoff})); raise SystemExit(8)
 if now >= int(handoff.get('deadline_at') or 0):
  handoff['status']='rejected'; handoff['decided_at']=now; handoff['reason']='handoff_deadline_expired'
  ok=False; code='deadline_expired'
 else:
  handoff['status']='committing'; handoff['committed_at']=now
elif action=='cancel':
 if claimant != handoff.get('claimant') or instance != handoff.get('claimant_instance_id'):
  print(json.dumps({'ok':False,'code':'not_claimant'})); raise SystemExit(9)
 if handoff.get('status') == 'pending_v2':
  handoff['status']='cancelled'; handoff['decided_at']=now; handoff['reason']='claimant_timeout'
 elif handoff.get('status') == 'committing':
  print(json.dumps({'ok':False,'code':'too_late','handoff':handoff})); raise SystemExit(10)
 else:
  print(json.dumps({'ok':False,'code':'invalid_state','handoff':handoff})); raise SystemExit(8)
elif action=='finish':
 if claimant != holder or (data.get('instance_id') and data.get('instance_id') != instance):
  print(json.dumps({'ok':False,'code':'not_owner'})); raise SystemExit(7)
 if handoff.get('status') != 'committing':
  print(json.dumps({'ok':False,'code':'invalid_state','handoff':handoff})); raise SystemExit(8)
 handoff['status']='acked'; handoff['decided_at']=now
 handoff['reason']=base64.b64decode(reason).decode('utf-8','replace') if reason != '-' else ''
 target=str(handoff.get('claimant') or ''); target_instance=str(handoff.get('claimant_instance_id') or '')
 if not target or not target_instance:
  print(json.dumps({'ok':False,'code':'invalid_claimant'})); raise SystemExit(11)
 current+=1
 data={'schema':2,'lease_protocol':2,'lease_ttl':int(lease_ttl),'name':name,'holder':target,'instance_id':target_instance,'generation':current,'renewed_at':now,'expires_at':now+int(lease_ttl),'evidence':{},'handoff':handoff}
elif action in ('ack','reject'):
 if claimant != holder or (data.get('instance_id') and data.get('instance_id') != instance):
  print(json.dumps({'ok':False,'code':'not_owner'})); raise SystemExit(7)
 if action=='ack' and handoff.get('status') != 'committing':
  print(json.dumps({'ok':False,'code':'invalid_state','handoff':handoff})); raise SystemExit(8)
 if action=='reject' and handoff.get('status') not in ('pending','committing'):
  print(json.dumps({'ok':False,'code':'invalid_state','handoff':handoff})); raise SystemExit(8)
 handoff['status']='acked' if action=='ack' else 'rejected'; handoff['decided_at']=now
 handoff['reason']=base64.b64decode(reason).decode('utf-8','replace') if reason != '-' else ''
else:
 print(json.dumps({'ok':False,'code':'invalid_action'})); raise SystemExit(6)
data['handoff']=handoff
fd,tmp=tempfile.mkstemp(prefix='.ownership-',dir=os.path.dirname(path))
with os.fdopen(fd,'w') as f: json.dump(data,f,separators=(',',':')); f.write('\n')
os.replace(tmp,path)
# Publish the legacy lock last.  It remains the authority, so a crash between
# the two writes leaves the old generation active instead of exposing a new
# holder without its instance/generation fence.
if action=='finish':
 with open(lock,'w') as f: f.write(f'{data["holder"]}@{now}@{current}\n')
print(json.dumps({'ok':ok,'code':code,'handoff':handoff,'generation':current}))
PY
"""
    # SSH flattens argv into one remote-shell command.  Quote every value read
    # from local config or the Hub sidecar (notably request_id) before it
    # reaches that shell.  A relative root preserves the login-home semantics
    # of remote_root() without relying on unquoted tilde expansion.
    remote_args = [
        "bash",
        "-s",
        "--",
        f"{cfg.user}/dual-tmux",
        name,
        action,
        request_id,
        cfg.client,
        instance_id(),
        str(generation),
        payload,
        str(int(timeout or 0)),
        str(OWNERSHIP_LEASE_TTL),
    ]
    result = _run(
        ssh_argv(cfg, connect_timeout=2) + [shlex.join(remote_args)], input=script
    )
    lines = (result.stdout or "").strip().splitlines()
    try:
        value = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        value = {}
    if not value:
        detail = (result.stderr or "handoff failed").strip().splitlines()
        raise SystemExit(f"[err] hub handoff: {detail[-1] if detail else 'failed'}")
    return value


def request_handoff(
    name: str,
    *,
    reason: str = "",
    timeout: int = 8,
    generation: int = 0,
    cfg: AppConfig | None = None,
) -> dict:
    lease = read_ownership(name, cfg) if not generation else None
    if lease is not None and lease["state"] != "foreign":
        return {"ok": False, "code": "not_foreign", "lease": lease}
    pending = (lease or {}).get("handoff") or {}
    cfg = cfg or load_config()
    if (
        pending.get("status") == "pending_v2"
        and pending.get("claimant") == cfg.client
        and pending.get("claimant_instance_id") == instance_id()
    ):
        return {
            "ok": True,
            "handoff": pending,
            "generation": int((lease or {}).get("generation") or generation),
            "idempotent": True,
        }
    request_id = uuid.uuid4().hex
    return _handoff_remote(
        name,
        "request",
        request_id=request_id,
        generation=int((lease or {}).get("generation") or generation),
        reason=reason,
        timeout=timeout,
        cfg=cfg,
    )


def begin_handoff(
    name: str,
    request_id: str,
    generation: int,
    *,
    cfg: AppConfig | None = None,
) -> dict:
    """Atomically commit an owner to park before the request deadline."""
    return _handoff_remote(
        name, "commit", request_id=request_id, generation=generation, cfg=cfg
    )


def cancel_handoff(
    name: str,
    request_id: str,
    generation: int,
    *,
    cfg: AppConfig | None = None,
) -> dict:
    """Cancel a pending request; an owner that already committed wins."""
    return _handoff_remote(
        name, "cancel", request_id=request_id, generation=generation, cfg=cfg
    )


def finish_handoff(
    name: str,
    request_id: str,
    generation: int,
    *,
    reason: str = "",
    cfg: AppConfig | None = None,
) -> dict:
    """Atomically acknowledge and transfer to the authenticated claimant."""
    return _handoff_remote(
        name,
        "finish",
        request_id=request_id,
        generation=generation,
        reason=reason,
        cfg=cfg,
    )


def decide_handoff(
    name: str,
    request_id: str,
    generation: int,
    *,
    accept: bool,
    reason: str = "",
    cfg: AppConfig | None = None,
) -> dict:
    return _handoff_remote(
        name,
        "ack" if accept else "reject",
        request_id=request_id,
        generation=generation,
        reason=reason,
        cfg=cfg,
    )


def holder_activity(holder: str, cfg: AppConfig | None = None) -> str:
    import tempfile

    cfg = cfg or load_config()
    host = SshTarget(cfg.server, cfg.ssh_port).dest
    tmp = Path(tempfile.mkdtemp()) / f"{holder}.log"
    result = _run(
        [
            "rsync",
            "-a",
            "-e",
            rsync_ssh(cfg),
            f"{host}:{remote_root(cfg)}/activity/{holder}.log",
            str(tmp),
        ]
    )
    if result.returncode != 0 or not tmp.is_file():
        return ""
    return tmp.read_text(encoding="utf-8", errors="replace")


def idle_enough(name: str, holder: str) -> bool:
    text = holder_activity(holder)
    return frozen_last_ticks(text, name, TICKS)


def _claim_ownership(
    name: str, force: bool = False, *, lease: dict | None = None
) -> dict:
    if not enabled():
        return {"holder": load_config().client, "generation": 1}
    lease = lease or read_ownership(name)
    holder = str(lease.get("holder") or "")
    age = int(lease.get("age_seconds") or 0)
    _generation = int(lease.get("generation") or 0)
    if lease.get("state") == "expired" and lease.get("lease_protocol") == 2:
        raise SystemExit(
            "[err] expired service ownership requires fenced fault takeover"
        )
    if lease.get("state") == "foreign" and lease.get("lease_protocol") == 2:
        raise SystemExit(
            "[err] active service ownership cannot be claimed directly; use handoff"
        )
    if lease.get("state") == "foreign":
        if not force and not idle_enough(name, holder):
            raise SystemExit(
                f"[err] {name} active on {holder} ({age}s ago). "
                f"last {TICKS} ticks still changing. "
                f"wait, dt drop there, or: dt resume {name} --force"
            )
        if not force:
            ui.info(f"idle  {name} on {holder}: last {TICKS} ticks frozen, taking over")
        kind, holder, age, _generation = _lock_remote(
            "claim",
            name,
            force=True,
            ttl=int(lease.get("lease_ttl") or LOCK_TTL),
        )
    else:
        kind, holder, age, _generation = _lock_remote(
            "claim", name, force=force, ttl=OWNERSHIP_LEASE_TTL
        )
    if kind == "HELD":
        raise SystemExit(
            f"[err] {name} active on {holder} ({age}s ago, TTL {LOCK_TTL}s). "
            f"wait, dt drop there, or: dt resume {name} --force"
        )
    ev.emit("hub.claim", name=name, holder=holder or load_config().client, force=force)
    return {
        "holder": holder or load_config().client,
        "generation": int(_generation or 0),
    }


def claim(name: str, force: bool = False) -> str:
    return str(_claim_ownership(name, force=force)["holder"])


def claim_generation(name: str, force: bool = False) -> dict:
    """Claim once and return the generation produced by the same Hub lock RPC."""
    if not enabled():
        return {"holder": load_config().client, "generation": 1}
    lease = read_ownership(name)
    if lease.get("state") == "expired" and lease.get("lease_protocol") == 2:
        raise SystemExit(
            "[err] expired service ownership requires fenced fault takeover"
        )
    if lease.get("state") == "foreign" and lease.get("lease_protocol") == 2:
        raise SystemExit(
            "[err] active service ownership cannot be claimed directly; use handoff"
        )
    if lease.get("state") == "foreign" and not force:
        raise SystemExit(
            f"[err] {name} active on {lease.get('holder') or 'unknown'} "
            f"({int(lease.get('age_seconds') or 0)}s ago, "
            f"TTL {int(lease.get('lease_ttl') or LOCK_TTL)}s)"
        )
    kind, holder, age, generation = _lock_remote(
        "claim", name, force=force, ttl=OWNERSHIP_LEASE_TTL
    )
    if kind == "HELD":
        raise SystemExit(
            f"[err] {name} active on {holder} ({age}s ago, TTL {LOCK_TTL}s)"
        )
    claimed = holder or load_config().client
    ev.emit("hub.claim", name=name, holder=claimed, force=force)
    return {"holder": claimed, "generation": int(generation or 0)}


def renew_ownership(
    name: str,
    generation: int,
    *,
    cfg: AppConfig | None = None,
) -> dict:
    """Renew this installation's short service-mode lease without stealing."""
    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        return {"holder": cfg.client, "generation": 1}
    kind = "ERR"
    holder = ""
    current = 0
    for attempt in range(5):
        kind, holder, _age, current = _lock_remote(
            "renew",
            name,
            cfg=cfg,
            ttl=OWNERSHIP_LEASE_TTL,
            expected_generation=generation,
        )
        if kind == "OK":
            break
        # Hub flock is deliberately non-blocking. Another local renewer or the
        # cache reader can hold it for a few milliseconds; that is contention,
        # not proof that this generation was fenced. Retry only the exact same
        # owner/generation, and still fail closed for every other response.
        if (
            kind != "HELD"
            or holder != cfg.client
            or int(current or 0) != int(generation or 0)
            or attempt == 4
        ):
            break
        time.sleep(0.1)
    if (
        kind != "OK"
        or holder != cfg.client
        or int(current or 0) != int(generation or 0)
    ):
        raise SystemExit(
            f"[err] ownership renewal fenced: holder={holder or 'unknown'} "
            f"generation={current}"
        )
    return {"holder": holder, "generation": int(current or 0)}


def _fault_takeover_remote(
    name: str,
    action: str,
    *,
    request_id: str,
    generation: int,
    cfg: AppConfig | None = None,
) -> dict:
    """Reserve or commit an expired generation under the Hub's flock.

    The reservation is the fence between service cleanup and transfer: only
    its claimant can publish the next generation, and ordinary renewals can
    no longer revive the expired owner once reservation succeeds.
    """
    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        return {"ok": True, "generation": 1, "holder": cfg.client}
    script = r"""
set -e
ROOT="$1"; NAME="$2"; ACTION="$3"; REQUEST="$4"; CLAIMANT="$5"; INSTANCE="$6"; EXPECTED="$7"; LEASE_TTL="$8"; TAKEOVER_TTL="$9"; LEGACY_TTL="${10}"; STALLED_TTL="${11}"
lock="$ROOT/locks/$NAME"; side="$ROOT/ownership/$NAME.json"
mkdir -p "$ROOT/locks" "$ROOT/ownership"; exec 9>>"$lock"; flock -x 9
python3 - "$lock" "$side" "$NAME" "$ACTION" "$REQUEST" "$CLAIMANT" "$INSTANCE" "$EXPECTED" "$LEASE_TTL" "$TAKEOVER_TTL" "$LEGACY_TTL" "$STALLED_TTL" <<'PY'
import json,os,sys,tempfile,time
lock,path,name,action,request,claimant,instance,expected,lease_ttl,takeover_ttl,legacy_ttl,stalled_ttl=sys.argv[1:]
expected=int(expected); lease_ttl=int(lease_ttl); takeover_ttl=int(takeover_ttl); legacy_ttl=int(legacy_ttl); stalled_ttl=int(stalled_ttl); now=int(time.time())
parts=open(lock).read().strip().split('@') if os.path.exists(lock) else []
holder=parts[0] if parts else ''
renewed=int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
generation=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 0
try:
 with open(path) as f: data=json.load(f)
except Exception: data={}
if not data:
 data={'schema':2,'lease_protocol':1,'name':name,'holder':holder,'instance_id':'','generation':generation,'renewed_at':renewed,'expires_at':renewed+legacy_ttl,'evidence':{},'handoff':None}
takeover=data.get('takeover') if isinstance(data.get('takeover'),dict) else None
if action=='repair':
 if takeover and takeover.get('status')=='committed' and takeover.get('request_id')==request and takeover.get('previous_holder')==holder and data.get('holder')==takeover.get('claimant') and int(data.get('generation') or 0)==generation+1:
  with open(lock,'w') as f: f.write(f'{data["holder"]}@{now}@{generation+1}\n')
  print(json.dumps({'ok':True,'code':'repaired','takeover':takeover,'generation':generation+1,'holder':data['holder']})); raise SystemExit(0)
 print(json.dumps({'ok':False,'code':'nothing_to_repair','generation':generation})); raise SystemExit(10)
if action in ('finish','cancel') and takeover and takeover.get('status')=='committed' and takeover.get('request_id')==request and takeover.get('claimant')==claimant and takeover.get('claimant_instance_id')==instance and int(data.get('generation') or 0)==expected+1:
 if generation==expected and holder==takeover.get('previous_holder'):
  with open(lock,'w') as f: f.write(f'{claimant}@{now}@{expected+1}\n')
 elif generation!=expected+1 or holder!=claimant:
  print(json.dumps({'ok':False,'code':'generation_conflict','generation':generation})); raise SystemExit(4)
 print(json.dumps({'ok':True,'code':'already_committed' if action=='cancel' else 'idempotent','takeover':takeover,'generation':expected+1,'holder':claimant})); raise SystemExit(0)
aligned=(data.get('holder')==holder and int(data.get('generation') or 0)==generation)
if not aligned:
 print(json.dumps({'ok':False,'code':'sidecar_conflict','generation':generation})); raise SystemExit(3)
if generation != expected:
 print(json.dumps({'ok':False,'code':'generation_conflict','generation':generation})); raise SystemExit(4)
if takeover and now-int(takeover.get('started_at') or 0)>takeover_ttl:
 takeover=None; data['takeover']=None
if action in ('begin','begin_stalled'):
 effective_ttl=lease_ttl if int(data.get('lease_protocol') or 1)==2 else legacy_ttl
 lease_active=renewed and (now-renewed < effective_ttl if effective_ttl != legacy_ttl else now-renewed <= effective_ttl)
 handoff=data.get('handoff') if isinstance(data.get('handoff'),dict) else None
 evidence=data.get('evidence') if isinstance(data.get('evidence'),dict) else {}
 stalled_ok=(action=='begin_stalled' and int(data.get('lease_protocol') or 1)==2 and handoff and handoff.get('status')=='cancelled' and handoff.get('reason')=='claimant_timeout' and handoff.get('claimant')==claimant and handoff.get('claimant_instance_id')==instance and int(evidence.get('sampled_at') or 0)>0 and now-int(evidence.get('sampled_at') or 0)>=stalled_ttl and int(handoff.get('requested_at') or 0)>int(evidence.get('sampled_at') or 0))
 if lease_active and not stalled_ok:
  print(json.dumps({'ok':False,'code':'lease_active','generation':generation})); raise SystemExit(5)
 if action=='begin_stalled' and not stalled_ok:
  print(json.dumps({'ok':False,'code':'stalled_owner_not_proven','generation':generation})); raise SystemExit(11)
 if handoff and handoff.get('status') in ('pending_v2','committing') and now < int(handoff.get('deadline_at') or 0) and (handoff.get('claimant')!=claimant or handoff.get('claimant_instance_id')!=instance):
  print(json.dumps({'ok':False,'code':'handoff_claimant_conflict','generation':generation})); raise SystemExit(6)
 if takeover:
  if takeover.get('request_id')==request and takeover.get('claimant')==claimant and takeover.get('claimant_instance_id')==instance:
   print(json.dumps({'ok':True,'code':'idempotent','takeover':takeover,'generation':generation})); raise SystemExit(0)
  print(json.dumps({'ok':False,'code':'takeover_pending','generation':generation})); raise SystemExit(7)
 takeover={'protocol':1,'request_id':request,'status':'fencing','claimant':claimant,'claimant_instance_id':instance,'previous_holder':holder,'started_at':now,'reason':'stalled_control_plane' if action=='begin_stalled' else 'lease_expired'}
 data['takeover']=takeover
elif action=='finish':
 if not takeover or takeover.get('request_id')!=request or takeover.get('claimant')!=claimant or takeover.get('claimant_instance_id')!=instance:
  print(json.dumps({'ok':False,'code':'reservation_lost','generation':generation})); raise SystemExit(8)
 generation+=1
 data={'schema':2,'lease_protocol':2,'lease_ttl':lease_ttl,'name':name,'holder':claimant,'instance_id':instance,'generation':generation,'renewed_at':now,'expires_at':now+lease_ttl,'evidence':{},'handoff':None,'takeover':{'protocol':1,'request_id':request,'status':'committed','claimant':claimant,'claimant_instance_id':instance,'previous_holder':holder,'started_at':takeover.get('started_at'),'committed_at':now}}
elif action=='cancel':
 if not takeover or takeover.get('request_id')!=request or takeover.get('claimant')!=claimant or takeover.get('claimant_instance_id')!=instance:
  print(json.dumps({'ok':False,'code':'reservation_lost','generation':generation})); raise SystemExit(8)
 data['takeover']=None
else:
 print(json.dumps({'ok':False,'code':'invalid_action'})); raise SystemExit(9)
fd,tmp=tempfile.mkstemp(prefix='.ownership-',dir=os.path.dirname(path))
with os.fdopen(fd,'w') as f: json.dump(data,f,separators=(',',':')); f.write('\n')
os.replace(tmp,path)
if action=='finish':
 with open(lock,'w') as f: f.write(f'{claimant}@{now}@{generation}\n')
print(json.dumps({'ok':True,'code':'','takeover':data.get('takeover'),'generation':generation,'holder':data.get('holder') or holder}))
PY
"""
    root = remote_root(cfg)
    remote_args = [
        "bash",
        "-s",
        "--",
        root.removeprefix("~/"),
        name,
        action,
        request_id,
        cfg.client,
        instance_id(),
        str(int(generation or 0)),
        str(OWNERSHIP_LEASE_TTL),
        str(FAULT_TAKEOVER_TTL),
        str(LOCK_TTL),
        str(STALLED_OWNER_EVIDENCE_TTL),
    ]
    result = _run(
        ssh_argv(cfg, connect_timeout=2) + [shlex.join(remote_args)], input=script
    )
    lines = (result.stdout or "").strip().splitlines()
    try:
        value = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        value = {}
    if not value:
        detail = (result.stderr or "fault takeover failed").strip().splitlines()
        raise SystemExit(
            f"[err] hub fault takeover: {detail[-1] if detail else 'failed'}"
        )
    return value


def reserve_fault_takeover(name: str, generation: int) -> dict:
    request_id = uuid.uuid4().hex
    try:
        value = _fault_takeover_remote(
            name, "begin", request_id=request_id, generation=generation
        )
    except SystemExit:
        # The Hub may have durably written the reservation while the SSH
        # response was lost.  Retry once with the same id; begin is idempotent.
        value = _fault_takeover_remote(
            name, "begin", request_id=request_id, generation=generation
        )
    if not value.get("ok"):
        raise SystemExit(
            f"[err] fault takeover rejected: {value.get('code') or 'unknown'}"
        )
    value["request_id"] = request_id
    return value


def reserve_stalled_takeover(name: str, generation: int) -> dict:
    """Fence a renewing owner only after its own handoff deadline expired."""
    request_id = uuid.uuid4().hex
    value = _fault_takeover_remote(
        name, "begin_stalled", request_id=request_id, generation=generation
    )
    if not value.get("ok"):
        raise SystemExit(
            f"[err] stalled takeover rejected: {value.get('code') or 'unknown'}"
        )
    value["request_id"] = request_id
    return value


def finish_fault_takeover(name: str, request_id: str, generation: int) -> dict:
    value = _fault_takeover_remote(
        name, "finish", request_id=request_id, generation=generation
    )
    if not value.get("ok"):
        raise SystemExit(
            f"[err] fault takeover commit rejected: {value.get('code') or 'unknown'}"
        )
    return value


def cancel_fault_takeover(name: str, request_id: str, generation: int) -> dict:
    return _fault_takeover_remote(
        name, "cancel", request_id=request_id, generation=generation
    )


def release(name: str, *, generation: int = 0) -> None:
    if not enabled():
        return
    kind, holder, _age, current = _lock_remote(
        "release", name, expected_generation=generation
    )
    if generation and kind == "HELD":
        raise SystemExit(
            f"[err] ownership release fenced: holder={holder or 'unknown'} generation={current}"
        )
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
