from __future__ import annotations

import copy
from typing import Any


class MemoryStateStore:
    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}

    def save(self, key: str, data: dict[str, Any]) -> None:
        self._data[key] = copy.deepcopy(data)

    def load(self, key: str) -> dict[str, Any] | None:
        data = self._data.get(key)
        return copy.deepcopy(data) if data is not None else None

    def delete(self, key: str) -> bool:
        if key not in self._data:
            return False
        del self._data[key]
        return True

    def exists(self, key: str) -> bool:
        return key in self._data

    def list_keys(self) -> list[str]:
        return list(self._data.keys())

    def clear(self) -> None:
        self._data.clear()
