from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import tmux as tmux_ops
from .config import AppConfig, load_config
from .identity import (
    SOURCE_HINT,
    USER_HINT,
    legal_source,
    legal_user,
    remote_sessions_root,
)
from .paths import config_path, home_dir, tombstones_dir, tunnels_dir
from .sshutil import SshTarget

SSH_HINT = "fix ~/.ssh/config and keys yourself; this CLI never writes SSH files"
INIT_HINT = "dt config --init --local --client tm_<id>  (or add --server/--user for Hub mode)"

TOMBSTONE_MAX_AGE_DAYS = 90


@dataclass
class Check:
    label: str
    ok: bool
    detail: str
    hint: str = ""
    required: bool = True


def probe_ssh(host: str, timeout: int = 5, port: int = 22) -> Check:
    if not shutil.which("ssh"):
        return Check("ssh", False, "ssh not in PATH", "install OpenSSH on the Client")
    if not host:
        return Check("ssh server", False, "no server in config", INIT_HINT)
    target = SshTarget(host, port)
    result = subprocess.run(
        [
            "ssh",
            *target.extra_args,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=%s" % timeout,
            "-o",
            "StrictHostKeyChecking=yes",
            target.dest,
            "echo ok",
        ],
        capture_output=True,
        text=True,
    )
    shown = target.dest if target.port == 22 else f"{target.dest}:{target.port}"
    if result.returncode == 0:
        return Check("ssh server", True, shown)
    err = (result.stderr or result.stdout or "failed").strip().splitlines()
    detail = err[-1] if err else "failed"
    return Check("ssh server", False, detail[:120], SSH_HINT)


def collect_checks() -> tuple[AppConfig | None, list[Check]]:
    checks: list[Check] = []
    path = config_path()
    cfg: AppConfig | None = None
    if not path.is_file():
        checks.append(Check("config", False, f"{path} missing", INIT_HINT))
    else:
        cfg = load_config()
        checks.append(Check("config", True, str(path)))
        if not legal_source(cfg.client):
            checks.append(Check("client", False, cfg.client or "(empty)", SOURCE_HINT))
        else:
            checks.append(Check("client", True, cfg.client))
        if cfg.hub_enabled:
            checks.append(Check("mode", True, "hub"))
            checks.append(Check("server", True, cfg.server))
            if not legal_user(cfg.user):
                checks.append(Check("user", False, cfg.user or "(empty)", USER_HINT))
            else:
                checks.append(Check("user", True, f"{cfg.user}  remote {remote_sessions_root(cfg.user)}"))
        elif cfg.server or cfg.user:
            checks.append(Check("mode", False, "partial Hub config", INIT_HINT))
        else:
            checks.append(Check("mode", True, "local-only"))
    home_dir().mkdir(parents=True, exist_ok=True)
    checks.append(Check("home", home_dir().is_dir(), str(home_dir())))
    if tmux_ops.have_tmux():
        checks.append(Check("tmux", True, shutil.which("tmux") or "tmux"))
    else:
        checks.append(Check("tmux", False, "not in PATH", "install tmux on the Client"))
    if cfg and cfg.hub_enabled:
        checks.append(probe_ssh(cfg.server, port=cfg.ssh_port))
    from .cron import dt_bin, installed

    if installed():
        checks.append(Check("tick cron", True, f"* * * * * {dt_bin()} tick"))
    else:
        checks.append(
            Check(
                "tick cron",
                False,
                "missing",
                "dt cron --install   (needed so another Client can see idle fingerprints)",
                required=False,
            )
        )
    return cfg, checks


def tombstone_clock(path) -> float:
    """Tombstone logical clock via fromisoformat, falling back to mtime."""
    try:
        value = str(
            json.loads(path.read_text(encoding="utf-8")).get("deleted_at") or ""
        )
        if value:
            return datetime.fromisoformat(value).timestamp()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def tunnel_clock(path) -> float:
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


def tombstone_checks() -> list[Check]:
    """Prune stale tombstones (>90d) and flag unresolved live/tombstone pairs."""
    checks: list[Check] = []
    root = tombstones_dir()
    pruned = 0
    kept = 0
    conflicts: list[str] = []
    if root.is_dir():
        cutoff = (datetime.now().astimezone() - timedelta(days=TOMBSTONE_MAX_AGE_DAYS)).timestamp()
        for path in sorted(root.glob("dt-*.json")):
            live = tunnels_dir() / path.name
            if live.is_file() and tombstone_clock(path) >= tunnel_clock(live):
                # Deletion still pending on this Client; the tombstone is the
                # only carrier of that fact, so it is not stale yet.
                conflicts.append(path.stem)
                kept += 1
                continue
            if tombstone_clock(path) < cutoff:
                path.unlink(missing_ok=True)
                pruned += 1
            else:
                kept += 1
    checks.append(
        Check(
            "tombstones",
            True,
            f"{kept} kept, {pruned} pruned (> {TOMBSTONE_MAX_AGE_DAYS}d)",
        )
    )
    if conflicts:
        checks.append(
            Check(
                "tombstone/live",
                False,
                f"deletion pending: {', '.join(conflicts)}",
                "run dt sync to converge this replica (or dt new to recreate)",
                required=False,
            )
        )
    return checks


def print_checks(checks: list[Check]) -> bool:
    from .ui import print_checks as rich_checks

    return rich_checks(checks)


def guide_if_needed(checks: list[Check]) -> None:
    if all(c.ok for c in checks):
        return
    from .ui import print_guide

    print_guide()


def all_ok(checks: list[Check]) -> bool:
    return all(c.ok for c in checks if c.required)


def ensure_ready(*, verbose: bool = False) -> AppConfig:
    cfg, checks = collect_checks()
    if verbose or not all_ok(checks):
        print_checks(checks)
    if not all_ok(checks):
        guide_if_needed(checks)
        raise SystemExit(1)
    assert cfg is not None
    return cfg
