from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import tomllib

from .identity import SOURCE_HINT, USER_HINT, legal_source, legal_user
from .paths import config_path, home_dir
from .sshutil import SshTarget, parse_ssh_target


@dataclass
class AppConfig:
    client: str = "client"
    server: str = ""
    user: str = ""
    workspace: str = "/workspace"
    ssh_port: int = 22

    def ssh_target(self) -> SshTarget:
        return SshTarget(self.server, self.ssh_port)

    @property
    def hub_enabled(self) -> bool:
        return bool(self.server and self.user)

    @property
    def mode(self) -> str:
        return "hub" if self.hub_enabled else "local"


def _parse_toml(text: str) -> AppConfig:
    data = tomllib.loads(text) if text.strip() else {}
    server = str(data.get("server") or "")
    user = str(data.get("user") or "")
    if server == "server" and user == "user":
        server = user = ""
    port = data.get("ssh_port", 22)
    try:
        ssh_port = int(port)
    except (TypeError, ValueError):
        ssh_port = 22
    return AppConfig(
        client=str(data.get("client") or "client"),
        server=server,
        user=user,
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
    return replace(
        cfg,
        client=client,
        server=server,
        user=user,
        workspace=workspace,
        ssh_port=ssh_port,
    )


def write_config(cfg: AppConfig) -> Path:
    validate_config(cfg)
    home_dir().mkdir(parents=True, exist_ok=True)
    path = config_path()
    lines = [
        f'client = "{cfg.client}"',
        f'workspace = "{cfg.workspace}"',
    ]
    if cfg.hub_enabled:
        lines[1:1] = [f'server = "{cfg.server}"', f'user = "{cfg.user}"']
    if cfg.hub_enabled and cfg.ssh_port and cfg.ssh_port != 22:
        lines.append(f"ssh_port = {cfg.ssh_port}")
    body = "\n".join(lines) + "\n"
    fd, raw = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def validate_config(cfg: AppConfig) -> None:
    if not legal_source(cfg.client):
        raise SystemExit(f"[err] client {SOURCE_HINT}")
    if bool(cfg.server) != bool(cfg.user):
        raise SystemExit(
            "[err] server and user must be set together, or both omitted for local mode"
        )
    if cfg.user and not legal_user(cfg.user):
        raise SystemExit(f"[err] user {USER_HINT}")
    if cfg.server:
        dest = cfg.server.strip()
        if any(c.isspace() for c in dest) or dest in ("server", ".", "-"):
            raise SystemExit("[err] server must be a Host alias or user@host")


def init_config(
    client: str,
    server: str = "",
    user: str = "",
    workspace: str = "/workspace",
) -> Path:
    return write_config(make_config(client, server, user, workspace))


def make_config(
    client: str,
    server: str = "",
    user: str = "",
    workspace: str = "/workspace",
) -> AppConfig:
    client = client.strip()
    server = server.strip()
    user = user.strip()
    if not client:
        raise SystemExit("[err] client is required")
    if not legal_source(client):
        raise SystemExit(f"[err] client {SOURCE_HINT}")
    if bool(server) != bool(user):
        raise SystemExit(
            "[err] server and user must be set together, or both omitted for local mode"
        )
    if not server:
        return AppConfig(client=client, workspace=workspace or "/workspace")
    target = parse_ssh_target(server)
    if not legal_user(user):
        raise SystemExit(f"[err] user {USER_HINT}")
    dest = target.stored
    if any(c.isspace() for c in dest) or dest in ("server", ".", "-"):
        raise SystemExit(
            "[err] server must be a Host alias, user@host, or `ssh -p N user@host`"
        )
    ssh_port = 22 if target.matched_alias else target.port
    return AppConfig(
        client=client,
        server=dest,
        user=user,
        workspace=workspace or "/workspace",
        ssh_port=ssh_port,
    )


def switch_config(current: AppConfig | None, candidate: AppConfig) -> Path:
    """Merge every affected Hub before atomically committing a mode change."""
    validate_config(candidate)
    from . import hub

    old = current if current and current.hub_enabled else None
    endpoint_changed = bool(
        old
        and (
            old.server != candidate.server
            or old.user != candidate.user
            or old.ssh_port != candidate.ssh_port
        )
    )
    if old and (endpoint_changed or not candidate.hub_enabled):
        hub.sync(old)
    if candidate.hub_enabled:
        hub.sync(candidate)
    return write_config(candidate)
