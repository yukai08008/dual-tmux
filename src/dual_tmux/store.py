from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .identity import legal_source


def tmux_root() -> Path:
    return Path.home() / "sessions" / "tmux"


def dt_dir(me: str) -> Path:
    path = tmux_root() / me / "dt"
    path.mkdir(parents=True, exist_ok=True)
    return path


def entry_dir(me: str) -> Path:
    path = tmux_root() / me / "entry"
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_dt(name: str) -> str:
    if not name:
        raise SystemExit("[err] 缺少隧道名")
    return name if name.startswith("dt-") else f"dt-{name}"


def legal_op(name: str) -> bool:
    return name.startswith("op_")


def legal_run(name: str) -> bool:
    return name.startswith("run_")


def default_names(short: str) -> tuple[str, str, str]:
    short = short.removeprefix("dt-")
    return f"dt-{short}", f"op_{short.replace('-', '_')}", f"run_{short.replace('-', '_')}"


def iter_dt_files() -> list[Path]:
    root = tmux_root()
    if not root.is_dir():
        return []
    files: list[Path] = []
    for src in sorted(root.iterdir()):
        if not src.is_dir() or not legal_source(src.name):
            continue
        folder = src / "dt"
        if not folder.is_dir():
            continue
        files.extend(sorted(folder.glob("dt-*.json")))
    return files


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def find_dt(name: str) -> Path:
    name = normalize_dt(name)
    for path in iter_dt_files():
        if path.stem == name:
            return path
    raise SystemExit(f"[err] 无此隧道: {name}")


def occupied(field: str, value: str, skip: str = "") -> str:
    for path in iter_dt_files():
        if path.stem == skip:
            continue
        data = load(path)
        if data.get(field) == value:
            return path.stem
    return ""


def latest_dt() -> Path:
    files = iter_dt_files()
    if not files:
        raise SystemExit("[err] 还没有隧道。先: dt new <名> --host tom7r --dir /workspace/...")
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def write_entry(me: str, session: str, cmd: str) -> Path:
    path = entry_dir(me) / f"{session}.cmd"
    path.write_text(cmd.rstrip() + "\n")
    return path
