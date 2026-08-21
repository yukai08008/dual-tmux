from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from .config import AppConfig, load_config
from .identity import SOURCE_HINT, USER_HINT, legal_source, legal_user, remote_sessions_root
from .paths import config_path, home_dir
from .sshutil import SshTarget
from . import tmux as tmux_ops

SSH_HINT = "fix ~/.ssh/config and keys yourself; this CLI never writes SSH files"
INIT_HINT = "dt config --init --client tm_<id> --server <ssh-host> --user <name>"


@dataclass
class Check:
    label: str
    ok: bool
    detail: str
    hint: str = ""


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
        if not cfg.server or cfg.server == "server":
            checks.append(Check("server", False, cfg.server or "(empty)", INIT_HINT))
        else:
            checks.append(Check("server", True, cfg.server))
        if not legal_user(cfg.user):
            checks.append(Check("user", False, cfg.user or "(empty)", USER_HINT))
        else:
            checks.append(Check("user", True, f"{cfg.user}  remote {remote_sessions_root(cfg.user)}"))
    home_dir().mkdir(parents=True, exist_ok=True)
    checks.append(Check("home", home_dir().is_dir(), str(home_dir())))
    if tmux_ops.have_tmux():
        checks.append(Check("tmux", True, shutil.which("tmux") or "tmux"))
    else:
        checks.append(Check("tmux", False, "not in PATH", "install tmux on the Client"))
    checks.append(probe_ssh(cfg.server if cfg else "", port=cfg.ssh_port if cfg else 22))
    return cfg, checks


def print_checks(checks: list[Check]) -> bool:
    ok = True
    for item in checks:
        mark = "OK " if item.ok else "ERR"
        if not item.ok:
            ok = False
        print(f"{mark}  {item.label:<12} {item.detail}")
        if not item.ok and item.hint:
            print(f"      -> {item.hint}")
    return ok


def guide_if_needed(checks: list[Check]) -> None:
    if all(c.ok for c in checks):
        return
    print()
    print("Client -> Server link is not ready.")
    print("Step 1 is three fields:")
    print("  client  legal local source name (tm_*)")
    print("  server  ssh Host alias already in ~/.ssh/config")
    print("  user    person id; remote persist is ~/<user>/sessions")
    print("This CLI never writes ~/.ssh or keys.")
    print()
    print(f"  {INIT_HINT}")
    print("  ssh <ssh-host>            # must succeed; dual-tmux does not set this up")
    print("  dt doctor")


def all_ok(checks: list[Check]) -> bool:
    return all(c.ok for c in checks)


def ensure_ready(*, verbose: bool = False) -> AppConfig:
    cfg, checks = collect_checks()
    if verbose or not all_ok(checks):
        print_checks(checks)
    if not all_ok(checks):
        guide_if_needed(checks)
        raise SystemExit(1)
    assert cfg is not None
    return cfg
