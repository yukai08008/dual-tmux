from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import entries_dir, tunnels_dir


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_dt(name: str) -> str:
    if not name:
        raise SystemExit("[err] missing tunnel name")
    return name if name.startswith("dt-") else f"dt-{name}"


def legal_op(name: str) -> bool:
    return name.startswith("op_")


def legal_run(name: str) -> bool:
    return name.startswith("run_")


def default_names(short: str) -> tuple[str, str, str]:
    short = short.removeprefix("dt-")
    safe = short.replace("-", "_")
    return f"dt-{short}", f"op_{safe}", f"run_{safe}"


def iter_dt_files() -> list[Path]:
    root = tunnels_dir()
    if not root.is_dir():
        return []
    return sorted(root.glob("dt-*.json"))


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def find_dt(name: str) -> Path:
    name = normalize_dt(name)
    path = tunnels_dir() / f"{name}.json"
    if path.is_file():
        return path
    raise SystemExit(f"[err] unknown tunnel: {name}")


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
        raise SystemExit("[err] no tunnels yet. Run: dt new <name>")
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def write_entry(session: str, cmd: str) -> Path:
    path = entries_dir() / f"{session}.cmd"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cmd.rstrip() + "\n")
    return path
