from __future__ import annotations

import base64
import hashlib
import json
import os
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
from .paths import entries_dir, tunnels_dir
from .sshutil import SshTarget


def ssh_argv(cfg: AppConfig | None = None) -> list[str]:
    cfg = cfg or load_config()
    target = SshTarget(cfg.server, cfg.ssh_port)
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", *target.extra_args, target.dest]


def rsync_ssh(cfg: AppConfig | None = None) -> str:
    cfg = cfg or load_config()
    target = SshTarget(cfg.server, cfg.ssh_port)
    extra = " ".join(target.extra_args)
    return f"ssh -o BatchMode=yes -o ConnectTimeout=8 {extra}".rstrip()


def remote_root(cfg: AppConfig | None = None) -> str:
    cfg = cfg or load_config()
    return remote_dt_root(cfg.user)


LOCK_TTL = 300


def enabled(cfg: AppConfig | None = None) -> bool:
    return (cfg or load_config()).hub_enabled


def _require_hub(cfg: AppConfig) -> None:
    if not cfg.hub_enabled:
        raise SystemExit(
            "[err] no Hub configured; attach one with: "
            "dt config --server <ssh-host> --user <name>"
        )


def _run(argv: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, input=input, check=False)


def _ensure_remote(cfg: AppConfig) -> None:
    _require_hub(cfg)
    dest = ssh_argv(cfg) + [
        (
            f"mkdir -p {remote_root(cfg)}/tunnels {remote_root(cfg)}/entries "
            f"{remote_root(cfg)}/locks {remote_root(cfg)}/activity "
            f"{remote_root(cfg)}/ownership"
        )
    ]
    result = _run(dest)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "ssh mkdir failed").strip().splitlines()
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


def _tunnel_time(path: Path) -> float:
    """Use the binding's logical clock, falling back to its file mtime."""
    try:
        value = str(json.loads(path.read_text(encoding="utf-8")).get("updated_at") or "")
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
        merged_mtime = max(
            preferred.stat().st_mtime_ns,
            other.stat().st_mtime_ns if other.is_file() else 0,
        ) + 1_000_000_000
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
    names = {path.name for root in (local_tunnels, hub_tunnels) for path in root.glob("dt-*.json")}
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
        path.name for root in (local_entries, hub_entries) for path in root.glob("run_*.cmd")
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
    parts = [(
        f"rm -f {root}/tunnels/{name}.json {root}/locks/{name} "
        f"{root}/ownership/{name}.json"
    )]
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
ROOT="$1"; NAME="$2"; ME="$3"; TTL="$4"; ACTION="$5"; FORCE="$6"; INSTANCE="$7"; EVIDENCE="$8"; EXPECTED="$9"
mkdir -p "$ROOT/locks" "$ROOT/ownership"
f="$ROOT/locks/$NAME"
side="$ROOT/ownership/$NAME.json"
now=$(date +%s)
holder=""; age=99999; generation=0
side_instance=""; side_generation=0
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
 print(str(x.get('instance_id') or '')+'|'+str(int(x.get('generation') or 0)))
except Exception: print('|0')
PY
)
  side_instance=$(printf '%s' "$values" | cut -d'|' -f1)
  side_generation=$(printf '%s' "$values" | cut -d'|' -f2)
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
value={"schema":2,"name":name,"holder":holder,"instance_id":instance,"generation":int(generation),"renewed_at":int(now),"expires_at":int(now)+int(ttl),"evidence":ev,"handoff":handoff}
os.makedirs(os.path.dirname(path),exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.ownership-',dir=os.path.dirname(path))
with os.fdopen(fd,'w') as f: json.dump(value,f,separators=(',',':')); f.write('\n')
os.replace(tmp,path)
PY
echo "OK $ME 0 ${generation:-1}"
"""
    result = _run(
        ssh_argv(cfg)
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
        ],
        input=script,
    )
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
        ssh_argv(cfg) + ["bash", "-s", "--", remote_root(cfg), name], input=script
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
    active = bool(holder and stamp and age <= LOCK_TTL)
    try:
        sidecar = json.loads(values.get("V2", b"") or b"{}")
    except (json.JSONDecodeError, TypeError):
        sidecar = {}
    aligned = bool(
        sidecar
        and sidecar.get("holder") == holder
        and int(sidecar.get("generation") or 0) == generation
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
        "state": "owned" if active and mine else ("foreign" if active else ("expired" if holder else "free")),
        "holder": holder if active else "",
        "instance_id": side_instance,
        "generation": generation,
        "renewed_at": stamp,
        "expires_at": stamp + LOCK_TTL if stamp else 0,
        "age_seconds": age,
        "evidence": sidecar.get("evidence") if aligned and isinstance(sidecar.get("evidence"), dict) else {},
        "handoff": sidecar.get("handoff") if aligned and isinstance(sidecar.get("handoff"), dict) else None,
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
    cfg: AppConfig | None = None,
) -> dict:
    cfg = cfg or load_config()
    payload = base64.b64encode(reason.encode("utf-8")).decode("ascii")
    script = r"""
set -e
ROOT="$1"; NAME="$2"; ACTION="$3"; REQUEST="$4"; CLAIMANT="$5"; INSTANCE="$6"; GENERATION="$7"; REASON="$8"
lock="$ROOT/locks/$NAME"; side="$ROOT/ownership/$NAME.json"
mkdir -p "$ROOT/locks" "$ROOT/ownership"; exec 9>>"$lock"; flock -x 9
python3 - "$lock" "$side" "$NAME" "$ACTION" "$REQUEST" "$CLAIMANT" "$INSTANCE" "$GENERATION" "$REASON" <<'PY'
import base64,json,os,sys,tempfile,time
lock,path,name,action,request,claimant,instance,generation,reason=sys.argv[1:]
parts=open(lock).read().strip().split('@') if os.path.exists(lock) else []
holder=parts[0] if parts else ''; current=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 0
try:
 with open(path) as f: data=json.load(f)
except Exception: data={}
if current != int(generation) or data.get('holder') != holder or int(data.get('generation') or 0) != current:
 print(json.dumps({'ok':False,'code':'generation_conflict','generation':current})); raise SystemExit(3)
handoff=data.get('handoff') if isinstance(data.get('handoff'),dict) else None
now=int(time.time())
if action=='request':
 if handoff and handoff.get('request_id') != request and handoff.get('status')=='pending':
  print(json.dumps({'ok':False,'code':'handoff_pending','handoff':handoff})); raise SystemExit(4)
 detail=base64.b64decode(reason).decode('utf-8','replace') if reason else ''
 handoff={'request_id':request,'status':'pending','claimant':claimant,'claimant_instance_id':instance,'requested_at':now,'reason':detail}
elif not handoff or handoff.get('request_id') != request:
 print(json.dumps({'ok':False,'code':'request_not_found'})); raise SystemExit(5)
elif action in ('ack','reject'):
 if claimant != holder or (data.get('instance_id') and data.get('instance_id') != instance):
  print(json.dumps({'ok':False,'code':'not_owner'})); raise SystemExit(7)
 handoff['status']='acked' if action=='ack' else 'rejected'; handoff['decided_at']=now
 handoff['reason']=base64.b64decode(reason).decode('utf-8','replace') if reason else ''
else:
 print(json.dumps({'ok':False,'code':'invalid_action'})); raise SystemExit(6)
data['handoff']=handoff
fd,tmp=tempfile.mkstemp(prefix='.ownership-',dir=os.path.dirname(path))
with os.fdopen(fd,'w') as f: json.dump(data,f,separators=(',',':')); f.write('\n')
os.replace(tmp,path); print(json.dumps({'ok':True,'handoff':handoff,'generation':current}))
PY
"""
    result = _run(
        ssh_argv(cfg)
        + [
            "bash", "-s", "--", remote_root(cfg), name, action, request_id,
            cfg.client, instance_id(), str(generation), payload,
        ],
        input=script,
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


def request_handoff(name: str, *, reason: str = "") -> dict:
    lease = read_ownership(name)
    if lease["state"] != "foreign":
        return {"ok": False, "code": "not_foreign", "lease": lease}
    pending = lease.get("handoff") or {}
    cfg = load_config()
    if (
        pending.get("status") == "pending"
        and pending.get("claimant") == cfg.client
        and pending.get("claimant_instance_id") == instance_id()
    ):
        return {
            "ok": True,
            "handoff": pending,
            "generation": int(lease.get("generation") or 0),
            "idempotent": True,
        }
    request_id = uuid.uuid4().hex
    return _handoff_remote(
        name, "request", request_id=request_id,
        generation=int(lease["generation"]), reason=reason,
    )


def decide_handoff(name: str, request_id: str, generation: int, *, accept: bool, reason: str = "") -> dict:
    return _handoff_remote(
        name, "ack" if accept else "reject", request_id=request_id,
        generation=generation, reason=reason,
    )


def holder_activity(holder: str, cfg: AppConfig | None = None) -> str:
    import tempfile

    cfg = cfg or load_config()
    host = SshTarget(cfg.server, cfg.ssh_port).dest
    tmp = Path(tempfile.mkdtemp()) / f"{holder}.log"
    result = _run(
        ["rsync", "-a", "-e", rsync_ssh(cfg), f"{host}:{remote_root(cfg)}/activity/{holder}.log", str(tmp)]
    )
    if result.returncode != 0 or not tmp.is_file():
        return ""
    return tmp.read_text(encoding="utf-8", errors="replace")


def idle_enough(name: str, holder: str) -> bool:
    text = holder_activity(holder)
    return frozen_last_ticks(text, name, TICKS)


def claim(name: str, force: bool = False) -> str:
    if not enabled():
        return load_config().client
    kind, holder, age, _generation = _lock_remote("read", name)
    if kind == "HELD" and holder and holder != load_config().client:
        if not force and not idle_enough(name, holder):
            raise SystemExit(
                f"[err] {name} active on {holder} ({age}s ago). "
                f"last {TICKS} ticks still changing. "
                f"wait, dt drop there, or: dt resume {name} --force"
            )
        if not force:
            ui.info(f"idle  {name} on {holder}: last {TICKS} ticks frozen, taking over")
        kind, holder, age, _generation = _lock_remote("claim", name, force=True)
    else:
        kind, holder, age, _generation = _lock_remote("claim", name, force=force)
    if kind == "HELD":
        raise SystemExit(
            f"[err] {name} active on {holder} ({age}s ago, TTL {LOCK_TTL}s). "
            f"wait, dt drop there, or: dt resume {name} --force"
        )
    ev.emit("hub.claim", name=name, holder=holder or load_config().client, force=force)
    return holder or load_config().client


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


def require_active(data: dict, force: bool = False) -> None:
    # Acquiring ownership is a preflight.  A rejection must never mutate local
    # panes: they may contain the user's only live view of the session.
    claim(data["name"], force=force)


def enforce_local() -> None:
    from .store import iter_dt_files, load

    cfg = load_config()
    if not cfg.hub_enabled:
        return
    me = cfg.client
    for path in iter_dt_files():
        data = load(path)
        name = data.get("name") or path.stem
        try:
            holder, _age = read_lock(name)
        except SystemExit:
            continue
        if holder and holder != me:
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
