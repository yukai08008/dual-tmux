from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from . import log as ev
from . import tmux as tmux_ops
from . import ui
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
    return subprocess.run(argv, capture_output=True, text=True, input=input)


def _ensure_remote(cfg: AppConfig) -> None:
    _require_hub(cfg)
    dest = ssh_argv(cfg) + [
        f"mkdir -p {remote_root(cfg)}/tunnels {remote_root(cfg)}/entries "
        f"{remote_root(cfg)}/locks {remote_root(cfg)}/activity"
    ]
    result = _run(dest)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "ssh mkdir failed").strip().splitlines()
        raise SystemExit(f"[err] hub mkdir: {err[-1] if err else 'failed'}")


def _rsync(src: str, dest: str, cfg: AppConfig, *, update: bool = False) -> None:
    argv = ["rsync", "-a"]
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
    parts = [f"rm -f {root}/tunnels/{name}.json {root}/locks/{name}"]
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
) -> tuple[str, str, int]:
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
            str(ttl),
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
    if not enabled():
        return "", 0
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
    if not enabled():
        return load_config().client
    kind, holder, age = _lock_remote("read", name)
    if kind == "HELD" and holder and holder != load_config().client:
        if not force and not idle_enough(name, holder):
            raise SystemExit(
                f"[err] {name} active on {holder} ({age}s ago). "
                f"last {TICKS} ticks still changing. "
                f"wait, dt drop there, or: dt resume {name} --force"
            )
        if not force:
            ui.info(f"idle  {name} on {holder}: last {TICKS} ticks frozen, taking over")
        kind, holder, age = _lock_remote("claim", name, force=True)
    else:
        kind, holder, age = _lock_remote("claim", name, force=force)
    if kind == "HELD":
        raise SystemExit(
            f"[err] {name} active on {holder} ({age}s ago, TTL {LOCK_TTL}s). "
            f"wait, dt drop there, or: dt resume {name} --force"
        )
    ev.emit("hub.claim", name=name, holder=holder or load_config().client, force=force)
    return holder or load_config().client


def release(name: str) -> None:
    if not enabled():
        return
    _lock_remote("release", name)
    ev.emit("hub.release", name=name)


FEISHU_LEASE_NAME = "__feishu_ws__"
FEISHU_LEASE_TTL = 15


def claim_feishu_lease(cfg: AppConfig | None = None) -> tuple[bool, str]:
    """Renew the single-active Feishu connector lease without stealing it."""
    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        return True, cfg.client
    kind, holder, _age = _lock_remote(
        "claim", FEISHU_LEASE_NAME, cfg=cfg, ttl=FEISHU_LEASE_TTL
    )
    return kind == "OK", holder


def release_feishu_lease(cfg: AppConfig | None = None) -> None:
    cfg = cfg or load_config()
    if cfg.hub_enabled:
        _lock_remote("release", FEISHU_LEASE_NAME, cfg=cfg, ttl=FEISHU_LEASE_TTL)


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
    try:
        claim(data["name"], force=force)
    except SystemExit:
        drop_local(data)
        raise


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


def sync_best_effort(wait: bool = False) -> None:
    if not enabled():
        return
    def _run_sync() -> None:
        try:
            dest = sync()
            ev.emit("hub.sync.ok", dest=dest)
        except SystemExit as exc:
            ev.emit("hub.sync.fail", error=str(exc))

    if wait:
        try:
            dest = sync()
            ui.info(f"hub sync  {dest}")
        except SystemExit as exc:
            ui.warn(f"hub sync skipped  {exc}")
        return
    threading.Thread(target=_run_sync, daemon=True).start()
