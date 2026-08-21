from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from .config import AppConfig, load_config
from .identity import remote_dt_root
from .activity import TICKS, activity_path, frozen_last_ticks
from .paths import entries_dir, tunnels_dir
from .sshutil import SshTarget
from . import log as ev
from . import tmux as tmux_ops
from . import ui


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


def _run(argv: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, input=input)


def _ensure_remote(cfg: AppConfig) -> None:
    dest = ssh_argv(cfg) + [
        f"mkdir -p {remote_root(cfg)}/tunnels {remote_root(cfg)}/entries "
        f"{remote_root(cfg)}/locks {remote_root(cfg)}/activity"
    ]
    result = _run(dest)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "ssh mkdir failed").strip().splitlines()
        raise SystemExit(f"[err] hub mkdir: {err[-1] if err else 'failed'}")


def _rsync(src: str, dest: str, cfg: AppConfig) -> None:
    result = _run(["rsync", "-a", "-e", rsync_ssh(cfg), src, dest])
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "rsync failed").strip().splitlines()
        raise SystemExit(f"[err] rsync: {err[-1] if err else 'failed'}")


def push(cfg: AppConfig | None = None) -> str:
    cfg = cfg or load_config()
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
    root = remote_root(cfg)
    tunnels_dir().mkdir(parents=True, exist_ok=True)
    entries_dir().mkdir(parents=True, exist_ok=True)
    host = SshTarget(cfg.server, cfg.ssh_port).dest
    _rsync(f"{host}:{root}/tunnels/", f"{tunnels_dir()}/", cfg)
    _rsync(f"{host}:{root}/entries/", f"{entries_dir()}/", cfg)
    ev.emit("hub.pull", host=host, root=root)
    return f"{host}:{root}"


def remove_remote(name: str, run: str = "", cfg: AppConfig | None = None) -> None:
    cfg = cfg or load_config()
    root = remote_root(cfg)
    parts = [f"rm -f {root}/tunnels/{name}.json {root}/locks/{name}"]
    if run:
        parts.append(f"rm -f {root}/entries/{run}.cmd")
    result = _run(ssh_argv(cfg) + ["; ".join(parts)])
    if result.returncode != 0:
        raise SystemExit("[err] hub rm failed")


def _lock_remote(action: str, name: str, force: bool = False, cfg: AppConfig | None = None) -> tuple[str, str, int]:
    cfg = cfg or load_config()
    script = r"""
set -e
ROOT="$1"; NAME="$2"; ME="$3"; TTL="$4"; ACTION="$5"; FORCE="$6"
mkdir -p "$ROOT/locks"
f="$ROOT/locks/$NAME"
now=$(date +%s)
holder=""; age=99999
if [ -f "$f" ]; then
  holder=$(cut -d@ -f1 "$f")
  ts=$(cut -d@ -f2 "$f")
  age=$((now - ${ts:-0}))
fi
if [ "$ACTION" = "read" ]; then
  if [ -n "$holder" ] && [ "$age" -le "$TTL" ]; then echo "HELD $holder $age"; else echo "FREE"; fi
  exit 0
fi
if [ "$ACTION" = "release" ]; then
  if [ "$holder" = "$ME" ]; then rm -f "$f"; echo "FREE"; else echo "HELD ${holder:-—} $age"; fi
  exit 0
fi
if [ -n "$holder" ] && [ "$holder" != "$ME" ] && [ "$age" -le "$TTL" ] && [ "$FORCE" != "1" ]; then
  echo "HELD $holder $age"
  exit 2
fi
echo "$ME@$now" > "$f"
echo "OK $ME 0"
"""
    result = _run(
        ssh_argv(cfg)
        + [
            "bash",
            "-s",
            "--",
            remote_root(cfg),
            name,
            cfg.client,
            str(LOCK_TTL),
            action,
            "1" if force else "0",
        ],
        input=script,
    )
    line = (result.stdout or "").strip().splitlines()
    text = line[-1] if line else ""
    parts = text.split()
    kind = parts[0] if parts else "ERR"
    holder = parts[1] if len(parts) > 1 else ""
    age = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    if result.returncode not in (0, 2) and kind not in {"OK", "HELD", "FREE"}:
        err = (result.stderr or text or "lock failed").strip().splitlines()
        raise SystemExit(f"[err] hub lock: {err[-1] if err else 'failed'}")
    return kind, holder, age


def read_lock(name: str) -> tuple[str, int]:
    kind, holder, age = _lock_remote("read", name)
    if kind == "HELD":
        return holder, age
    return "", 0


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
    kind, holder, age = _lock_remote("read", name)
    if kind == "HELD" and holder and holder != load_config().client:
        if not force and not idle_enough(name, holder):
            raise SystemExit(
                f"[err] {name} active on {holder} ({age}s ago). "
                f"last {TICKS} ticks still changing. "
                f"dt park there, or: dt resume {name} --force"
            )
        if not force:
            ui.info(f"idle  {name} on {holder}: last {TICKS} ticks frozen, taking over")
        kind, holder, age = _lock_remote("claim", name, force=True)
    else:
        kind, holder, age = _lock_remote("claim", name, force=force)
    if kind == "HELD":
        raise SystemExit(
            f"[err] {name} active on {holder} ({age}s ago, TTL {LOCK_TTL}s). "
            f"dt park there, or: dt resume {name} --force"
        )
    ev.emit("hub.claim", name=name, holder=holder or load_config().client, force=force)
    return holder or load_config().client


def release(name: str) -> None:
    _lock_remote("release", name)
    ev.emit("hub.release", name=name)


def park_local(data: dict) -> list[str]:
    parked = []
    for key in ("op", "run"):
        name = data.get(key) or ""
        got = tmux_ops.park_session(name) if name else ""
        if got:
            parked.append(f"{name}->{got}")
    if parked:
        ev.emit("dt.park", name=data.get("name"), sessions=",".join(parked))
        ui.info(f"parked  {' '.join(parked)}")
    return parked


def require_active(data: dict, force: bool = False) -> None:
    try:
        claim(data["name"], force=force)
    except SystemExit:
        park_local(data)
        raise


def enforce_local() -> None:
    from .store import iter_dt_files, load

    me = load_config().client
    for path in iter_dt_files():
        data = load(path)
        name = data.get("name") or path.stem
        try:
            holder, _age = read_lock(name)
        except SystemExit:
            continue
        if holder and holder != me:
            park_local(data)


def push_best_effort(wait: bool = False) -> None:
    def _run_push() -> None:
        try:
            dest = push()
            ev.emit("hub.push.ok", dest=dest)
        except SystemExit as exc:
            ev.emit("hub.push.fail", error=str(exc))

    if wait:
        try:
            dest = push()
            ui.info(f"hub push  {dest}")
        except SystemExit as exc:
            ui.warn(f"hub push skipped  {exc}")
        return
    threading.Thread(target=_run_push, daemon=True).start()
