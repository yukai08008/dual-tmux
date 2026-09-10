from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FileStateStore:
    """Baseline single-process, low-frequency JSON store; not Hub-safe."""

    def __init__(self, base_dir: str | Path = ".state_store"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self.base_dir / f"{safe_key}.json"

    def save(self, key: str, data: dict[str, Any]) -> None:
        self._path(key).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def load(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_keys(self) -> list[str]:
        return [path.stem for path in self.base_dir.glob("*.json")]
