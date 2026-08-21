from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from .identity import SOURCE_HINT, legal_source
from .paths import config_path, home_dir


@dataclass
class AppConfig:
    client: str = "client"
    server: str = "server"
    workspace: str = "/workspace"


def _parse_toml(text: str) -> AppConfig:
    data = tomllib.loads(text) if text.strip() else {}
    return AppConfig(
        client=str(data.get("client") or "client"),
        server=str(data.get("server") or "server"),
        workspace=str(data.get("workspace") or "/workspace"),
    )


def load_config() -> AppConfig:
    path = config_path()
    cfg = AppConfig()
    if path.is_file():
        cfg = _parse_toml(path.read_text())
    client = os.environ.get("DT_CLIENT", "").strip() or cfg.client
    server = os.environ.get("DT_SERVER", "").strip() or cfg.server
    workspace = os.environ.get("DT_WORKSPACE", "").strip() or cfg.workspace
    return replace(cfg, client=client, server=server, workspace=workspace)


def write_config(cfg: AppConfig) -> Path:
    home_dir().mkdir(parents=True, exist_ok=True)
    path = config_path()
    body = (
        f'client = "{cfg.client}"\n'
        f'server = "{cfg.server}"\n'
        f'workspace = "{cfg.workspace}"\n'
    )
    path.write_text(body)
    return path


def init_config(client: str, server: str, workspace: str = "/workspace") -> Path:
    client = client.strip()
    server = server.strip()
    if not client or not server:
        raise SystemExit("[err] client and server are required")
    if not legal_source(client):
        raise SystemExit(f"[err] client {SOURCE_HINT}")
    if any(c.isspace() for c in server) or server in ("server", ".", "-"):
        raise SystemExit("[err] server must be an ssh Host alias from ~/.ssh/config")
    return write_config(AppConfig(client=client, server=server, workspace=workspace or "/workspace"))
