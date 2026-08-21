from __future__ import annotations

import subprocess

from .config import AppConfig, load_config
from .identity import remote_dt_root
from .paths import entries_dir, tunnels_dir
from .sshutil import SshTarget
from . import log as ev
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


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def _ensure_remote(cfg: AppConfig) -> None:
    dest = ssh_argv(cfg) + [f"mkdir -p {remote_root(cfg)}/tunnels {remote_root(cfg)}/entries"]
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
    parts = [f"rm -f {root}/tunnels/{name}.json"]
    if run:
        parts.append(f"rm -f {root}/entries/{run}.cmd")
    result = _run(ssh_argv(cfg) + ["; ".join(parts)])
    if result.returncode != 0:
        raise SystemExit("[err] hub rm failed")


def push_best_effort() -> None:
    try:
        dest = push()
        ui.info(f"hub push  {dest}")
    except SystemExit as exc:
        ui.warn(f"hub push skipped  {exc}")
