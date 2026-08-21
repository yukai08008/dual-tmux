from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "session-persist"


def name_file() -> Path:
    return config_dir() / "name"


def legal_source(name: str) -> bool:
    return name.startswith("tm_") and all(c.isalnum() or c in "._-" for c in name[3:])


def require_me() -> str:
    env = os.environ.get("SYNC_NAME", "").strip()
    raw = env or (name_file().read_text().strip() if name_file().is_file() else "")
    if not raw:
        raise SystemExit(
            "[err] 未设置来源名: echo tm_andy_ouc > ~/.config/session-persist/name"
        )
    if not legal_source(raw):
        raise SystemExit(f"[err] 非法来源名 '{raw}': 必须以 tm_ 开头")
    return raw


def init_name(name: str) -> Path:
    if not legal_source(name):
        raise SystemExit(f"[err] 非法来源名 '{name}': 必须以 tm_ 开头")
    path = name_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name + "\n")
    return path
