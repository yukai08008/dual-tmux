"""Declare valid state transitions and their guards/actions."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

S = TypeVar("S", bound=Enum)
GuardFn = Callable[..., bool]
ActionFn = Callable[..., None]


class TransitionDef:
    def __init__(
        self,
        event: str,
        guard: GuardFn | None = None,
        on_exit: ActionFn | None = None,
        on_enter: ActionFn | None = None,
    ):
        self.event = event
        self.guard = guard
        self.on_exit = on_exit
        self.on_enter = on_enter


class Graph:
    """Reusable static transition graph."""

    def __init__(
        self,
        transitions: dict[tuple[S, S], dict[str, Any]],
        initial: S,
    ):
        self.initial = initial
        self._transitions: dict[tuple[S, S], TransitionDef] = {}
        self._event_index: dict[str, list[tuple[S, S]]] = {}
        for (from_state, to_state), config in transitions.items():
            definition = TransitionDef(
                event=config.get("event", ""),
                guard=config.get("guard"),
                on_exit=config.get("on_exit"),
                on_enter=config.get("on_enter"),
            )
            self._transitions[(from_state, to_state)] = definition
            self._event_index.setdefault(definition.event, []).append(
                (from_state, to_state)
            )

    def find_transition(
        self, current: S, event: str
    ) -> tuple[S, S, TransitionDef] | None:
        for from_state, to_state in self._event_index.get(event, []):
            if from_state == current:
                return from_state, to_state, self._transitions[(from_state, to_state)]
        return None

    def available_events(self, current: S) -> list[str]:
        return sorted(
            {
                definition.event
                for (from_state, _), definition in self._transitions.items()
                if from_state == current
            }
        )

    def transitions_from(self, state: S) -> list[tuple[S, TransitionDef]]:
        return [
            (to_state, definition)
            for (from_state, to_state), definition in self._transitions.items()
            if from_state == state
        ]

    def all_transitions(self) -> list[tuple[S, S, TransitionDef]]:
        return [
            (from_state, to_state, definition)
            for (from_state, to_state), definition in self._transitions.items()
        ]

    def to_mermaid(self) -> str:
        lines = ["stateDiagram-v2"]
        for (from_state, to_state), definition in self._transitions.items():
            guard = " [guard]" if definition.guard else ""
            lines.append(
                f"    {from_state.value} --> {to_state.value} : "
                f"{definition.event}{guard}"
            )
        return "\n".join(lines)
