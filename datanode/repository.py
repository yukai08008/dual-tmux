"""Strongly-typed repository for TunnelNode entities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dual_tmux.paths import tunnels_dir
from dual_tmux.store import normalize_dt

from .adapters import from_legacy_tunnel, to_legacy_tunnel
from .models import TunnelNode


class TunnelRepository:
    """Repository managing TunnelNode persistence and validation.

    Ensures all disk I/O converts cleanly between raw JSON and strongly-typed
    TunnelNode domain entities.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root

    def _tunnels_dir(self) -> Path:
        return self.root if self.root is not None else tunnels_dir()

    def _path_for(self, name: str) -> Path:
        norm = normalize_dt(name)
        return self._tunnels_dir() / f"{norm}.json"

    def list_paths(self) -> list[Path]:
        directory = self._tunnels_dir()
        if not directory.is_dir():
            return []
        return sorted(directory.glob("dt-*.json"))

    def list(self) -> list[TunnelNode]:
        """Load and validate all tunnel nodes from disk."""
        nodes: list[TunnelNode] = []
        for path in self.list_paths():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                nodes.append(from_legacy_tunnel(raw))
            except (OSError, ValueError):
                continue
        return nodes

    def get(self, name: str) -> TunnelNode:
        """Get and validate a TunnelNode by name."""
        path = self._path_for(name)
        if not path.is_file():
            raise KeyError(f"Tunnel not found: {name}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return from_legacy_tunnel(raw)

    def get_or_none(self, name: str) -> TunnelNode | None:
        """Get a TunnelNode if it exists and is valid, or None."""
        try:
            return self.get(name)
        except (KeyError, OSError, ValueError):
            return None

    def get_raw(self, name: str) -> dict[str, Any]:
        """Get raw legacy dict record."""
        path = self._path_for(name)
        if not path.is_file():
            raise KeyError(f"Tunnel not found: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, node: TunnelNode, *, base: dict[str, Any] | None = None) -> Path:
        """Save a TunnelNode to disk, validating invariants and projecting format."""
        path = self._path_for(node.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if base is None and path.is_file():
            try:
                base = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                base = None

        record = to_legacy_tunnel(node, base=base)
        payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        path.write_text(payload, encoding="utf-8")
        return path

    def save_raw(self, data: dict[str, Any]) -> TunnelNode:
        """Validate raw dictionary as a TunnelNode and persist to disk."""
        node = from_legacy_tunnel(data)
        self.save(node, base=data)
        return node

    def delete(self, name: str) -> bool:
        """Delete a tunnel file if it exists."""
        path = self._path_for(name)
        if path.is_file():
            path.unlink()
            return True
        return False

    def exists(self, name: str) -> bool:
        return self._path_for(name).is_file()
