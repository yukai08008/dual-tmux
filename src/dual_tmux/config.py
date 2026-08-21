from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from .identity import SOURCE_HINT, USER_HINT, legal_source, legal_user
from .paths import config_path, home_dir
from .sshutil import SshTarget, parse_ssh_target


@dataclass
class AppConfig:
    client: str = "client"
    server: str = "server"
    user: str = "user"
    workspace: str = "/workspace"
    ssh_port: int = 22

    def ssh_target(self) -> SshTarget:
        return SshTarget(self.server, self.ssh_port)


def _parse_toml(text: str) -> AppConfig:
    data = tomllib.loads(text) if text.strip() else {}
    port = data.get("ssh_port", 22)
    try:
        ssh_port = int(port)
    except (TypeError, ValueError):
        ssh_port = 22
    return AppConfig(
        client=str(data.get("client") or "client"),
        server=str(data.get("server") or "server"),
        user=str(data.get("user") or "user"),
        workspace=str(data.get("workspace") or "/workspace"),
        ssh_port=ssh_port or 22,
    )


def load_config() -> AppConfig:
    path = config_path()
    cfg = AppConfig()
    if path.is_file():
        cfg = _parse_toml(path.read_text())
    client = os.environ.get("DT_CLIENT", "").strip() or cfg.client
    server = os.environ.get("DT_SERVER", "").strip() or cfg.server
    user = os.environ.get("DT_USER", "").strip() or cfg.user
    workspace = os.environ.get("DT_WORKSPACE", "").strip() or cfg.workspace
    env_port = os.environ.get("DT_SSH_PORT", "").strip()
    ssh_port = int(env_port) if env_port.isdigit() else cfg.ssh_port
    return replace(cfg, client=client, server=server, user=user, workspace=workspace, ssh_port=ssh_port)


def write_config(cfg: AppConfig) -> Path:
    home_dir().mkdir(parents=True, exist_ok=True)
    path = config_path()
    lines = [
        f'client = "{cfg.client}"',
        f'server = "{cfg.server}"',
        f'user = "{cfg.user}"',
        f'workspace = "{cfg.workspace}"',
    ]
    if cfg.ssh_port and cfg.ssh_port != 22:
        lines.append(f"ssh_port = {cfg.ssh_port}")
    path.write_text("\n".join(lines) + "\n")
    return path


def init_config(
    client: str,
    server: str,
    user: str,
    workspace: str = "/workspace",
) -> Path:
    client = client.strip()
    target = parse_ssh_target(server)
    user = user.strip()
    if not client or not target.dest or not user:
        raise SystemExit("[err] client, server, and user are required")
    if not legal_source(client):
        raise SystemExit(f"[err] client {SOURCE_HINT}")
    if not legal_user(user):
        raise SystemExit(f"[err] user {USER_HINT}")
    dest = target.dest
    if any(c.isspace() for c in dest) or dest in ("server", ".", "-"):
        raise SystemExit("[err] server must be a Host alias, user@host, or `ssh -p N user@host`")
    return write_config(
        AppConfig(
            client=client,
            server=dest,
            user=user,
            workspace=workspace or "/workspace",
            ssh_port=target.port,
        )
    )
