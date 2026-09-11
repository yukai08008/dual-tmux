"""Declarative lifecycle hooks for runtime FSMs (Binding & Resume).

Following fsm-agenty specifications:
- Guards are pure and side-effect free.
- on_enter/on_exit manage memory state transitions.
- External system I/O and business side-effects (e.g. parameter refresh,
  TunnelNode projection, run entry persistence) are explicitly encapsulated
  in declarative Hook classes.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any, Protocol

from datanode.adapters import from_legacy_tunnel, to_legacy_tunnel
from datanode.models import BindingAttemptNode


class BindingHook(Protocol):
    """Protocol for binding lifecycle hooks."""

    def __call__(self, node: BindingAttemptNode, context: dict[str, Any]) -> None: ...


class TunnelProjectionHook:
    """Project a proven working copy through TunnelNode and persist run entries.

    Used when freeze or trigger rebuilds bullet:
    1. Validates working copy via TunnelNode schema.
    2. Projects back to legacy dict format, preserving workpoints.
    3. Persists run entry for bullet sessions.
    4. Commits changes to the master target dict.
    """

    def __init__(
        self,
        target: dict[str, Any],
        working: dict[str, Any],
        side: str,
        holder: str = "",
        persist_entry_fn: Callable[[str, str], None] | None = None,
    ) -> None:
        self.target = target
        self.working = working
        self.side = side
        self.holder = holder
        self.persist_entry_fn = persist_entry_fn

    def __call__(self, node: BindingAttemptNode, context: dict[str, Any]) -> None:
        self.execute()

    def execute(self) -> dict[str, Any]:
        working_copy = copy.deepcopy(self.working)
        side_info = working_copy.setdefault(self.side, {})
        if self.holder:
            side_info["bound_by_client"] = self.holder

        # Validate through strong-typed DataNode
        tunnel_node = from_legacy_tunnel(working_copy)
        projected = to_legacy_tunnel(tunnel_node, base=self.target)

        # Preserve runtime discovered workpoints
        for key in ("op_point", "run_point"):
            if key in working_copy:
                projected[key] = copy.deepcopy(working_copy[key])

        if self.side == "bullet" and self.persist_entry_fn is not None:
            self.persist_entry_fn(
                str(projected.get("run") or ""),
                str((projected.get("runtime") or {}).get("cmd") or ""),
            )

        self.target.update(projected)
        return projected
