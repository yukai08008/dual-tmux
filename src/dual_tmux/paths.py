from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    return Path(os.environ.get("DUAL_TMUX_HOME", Path.home() / ".dual-tmux")).expanduser()


def config_path() -> Path:
    return home_dir() / "config.toml"


def tunnels_dir() -> Path:
    return home_dir() / "tunnels"


def entries_dir() -> Path:
    return home_dir() / "entries"


def events_path() -> Path:
    return home_dir() / "events.jsonl"


def skills_dir() -> Path:
    return home_dir() / "skills"


def ops_root() -> Path:
    return home_dir() / "ops"


def activity_path() -> Path:
    return home_dir() / "activity.log"
