"""Pure BindingAttempt FSM for freeze and bullet/trigger rebuild.

Workers do tmux/SSH I/O, then report events. Guards have no side effects.
Tunnel JSON mutation happens only after live_session_proven, in the worker
commit hook, then commit_succeeded.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from datanode.fsm_core import Graph, Machine, StateStore, TransitionError
from datanode.models import (
    AgentRole,
    BindingAttemptNode,
    BindingAttemptState,
    BindingIntent,
)

SCHEMA_VERSION = 1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BindingEvent(str, Enum):
    REQUESTED = "requested"
    LIVE_SESSION_PROVEN = "live_session_proven"
    LIVE_SESSION_MISSING = "live_session_missing"
    COMMIT_SUCCEEDED = "commit_succeeded"
    COMMIT_FAILED = "commit_failed"


class BindingError(StrictModel):
    code: str = Field(min_length=1)
    message: str = ""


class Requested(StrictModel):
    event: Literal["requested"] = "requested"
    holder: str = ""
    local_mode: bool = True
    occupancy_holder: str = ""


class LiveSessionProven(StrictModel):
    event: Literal["live_session_proven"] = "live_session_proven"
    session_id: str = Field(min_length=1)
    tool: str = "opencode"
    directory: str = ""
    other_session_id: str = ""
    rebuild: bool = False
    endpoint_kind: Literal["", "local", "ssh", "docker"] = ""
    endpoint_server: str = ""
    endpoint_container: str = ""
    endpoint_directory: str = ""


class LiveSessionMissing(StrictModel):
    event: Literal["live_session_missing"] = "live_session_missing"
    error: BindingError


class CommitSucceeded(StrictModel):
    event: Literal["commit_succeeded"] = "commit_succeeded"


class CommitFailed(StrictModel):
    event: Literal["commit_failed"] = "commit_failed"
    error: BindingError


BindingEventPayload = Annotated[
    Requested
    | LiveSessionProven
    | LiveSessionMissing
    | CommitSucceeded
    | CommitFailed,
    Field(discriminator="event"),
]
PAYLOAD_ADAPTER = TypeAdapter(BindingEventPayload)


def _payload(context: dict) -> BindingEventPayload:
    return context["payload"]


def _can_prove(context: dict) -> bool:
    payload = _payload(context)
    node: BindingAttemptNode = context["node"]
    if not isinstance(payload, LiveSessionProven):
        return False
    local_mode = bool(context.get("local_mode", True))
    occupancy_holder = str(context.get("occupancy_holder") or "")
    holder = node.holder or str(context.get("holder") or "")
    if not local_mode and occupancy_holder and occupancy_holder != holder:
        return False
    if payload.other_session_id and payload.session_id == payload.other_session_id:
        return False
    if payload.rebuild and node.previous_session_id == payload.session_id:
        return False
    if node.role is AgentRole.BULLET and payload.endpoint_kind == "docker":
        return bool(
            payload.endpoint_server
            and payload.endpoint_container
            and (payload.endpoint_directory or payload.directory)
        )
    return True


def _enter(target: BindingAttemptState):
    def update(context: dict) -> None:
        node: BindingAttemptNode = context["node"]
        payload = _payload(context)
        changes: dict = {"state": target}
        if isinstance(payload, Requested):
            context["local_mode"] = payload.local_mode
            context["occupancy_holder"] = payload.occupancy_holder
            context["holder"] = payload.holder
            if payload.holder:
                changes["holder"] = payload.holder
        elif isinstance(payload, LiveSessionProven):
            changes["candidate_session_id"] = payload.session_id
            changes["candidate_directory"] = payload.directory
            changes["intent"] = (
                BindingIntent.REBUILD if payload.rebuild else BindingIntent.FREEZE
            )
            changes["error"] = ""
        elif isinstance(payload, (LiveSessionMissing, CommitFailed)):
            changes["error"] = payload.error.message or payload.error.code
        elif isinstance(payload, CommitSucceeded):
            changes["error"] = ""
        context["node"] = BindingAttemptNode.model_validate(
            node.model_copy(update=changes).model_dump(exclude={"identity"})
        )

    return update


def binding_graph() -> Graph:
    event = BindingEvent
    state = BindingAttemptState
    return Graph(
        {
            (state.CREATED, state.PROVING): {
                "event": event.REQUESTED.value,
                "on_enter": _enter(state.PROVING),
            },
            (state.PROVING, state.COMMITTING): {
                "event": event.LIVE_SESSION_PROVEN.value,
                "guard": _can_prove,
                "on_enter": _enter(state.COMMITTING),
            },
            (state.PROVING, state.REJECTED): {
                "event": event.LIVE_SESSION_MISSING.value,
                "on_enter": _enter(state.REJECTED),
            },
            (state.COMMITTING, state.BOUND): {
                "event": event.COMMIT_SUCCEEDED.value,
                "on_enter": _enter(state.BOUND),
            },
            (state.COMMITTING, state.FAILED): {
                "event": event.COMMIT_FAILED.value,
                "on_enter": _enter(state.FAILED),
            },
        },
        initial=state.CREATED,
    )


class BindingMachine:
    """Typed wrapper that persists every successful pure state transition."""

    def __init__(self, node: BindingAttemptNode, store: StateStore):
        self.store = store
        self.core = Machine(binding_graph(), context={"node": node})
        self.core.state = node.state
        self._commit_hooks: list[Callable[[BindingAttemptNode, dict], None]] = []

    def register_commit_hook(
        self, hook: Callable[[BindingAttemptNode, dict], None]
    ) -> None:
        """Register a hook to be executed during the commit transition."""
        self._commit_hooks.append(hook)

    def commit_proven(
        self, payload: dict | StrictModel
    ) -> BindingAttemptState:
        """Coordinate: PROVING -> LIVE_SESSION_PROVEN -> run commit hooks -> COMMIT_SUCCEEDED."""
        self.send(BindingEvent.LIVE_SESSION_PROVEN, payload)
        try:
            for hook in self._commit_hooks:
                hook(self.node, self.core.context)
            return self.send(BindingEvent.COMMIT_SUCCEEDED, {})
        except Exception as exc:
            if self.state is BindingAttemptState.COMMITTING:
                self.send(
                    BindingEvent.COMMIT_FAILED,
                    {"error": {"code": "commit_rejected", "message": str(exc)}},
                )
            raise

    @property
    def node(self) -> BindingAttemptNode:
        return self.core.context["node"]

    @property
    def state(self) -> BindingAttemptState:
        return self.core.state

    @property
    def key(self) -> str:
        return f"binding:{self.node.attempt_id}"

    def send(
        self, event: BindingEvent | str, payload: dict | StrictModel
    ) -> BindingAttemptState:
        event_name = event.value if isinstance(event, BindingEvent) else str(event)
        raw = (
            payload.model_dump(mode="json")
            if isinstance(payload, BaseModel)
            else payload
        )
        value = PAYLOAD_ADAPTER.validate_python({**raw, "event": event_name})
        before_state = self.core.state
        before_node = self.node
        before_log = self.core.log
        before_ctx = {
            key: self.core.context.get(key)
            for key in ("payload", "local_mode", "occupancy_holder", "holder")
        }
        self.core.context["payload"] = value
        try:
            result = self.core.send(event_name)
            self._persist()
        except Exception:
            self.core.state = before_state
            self.core.context["node"] = before_node
            self.core._log = before_log
            for key, old in before_ctx.items():
                if old is None:
                    self.core.context.pop(key, None)
                else:
                    self.core.context[key] = old
            raise
        return BindingAttemptState(result.value)

    def _persist(self) -> None:
        self.store.save(
            self.key,
            {
                "schema_version": SCHEMA_VERSION,
                "graph": "binding",
                "state": self.state.value,
                "node": self.node.model_dump(mode="json", exclude={"identity"}),
                "transitions": self.core.log,
                "local_mode": bool(self.core.context.get("local_mode", True)),
                "occupancy_holder": str(
                    self.core.context.get("occupancy_holder") or ""
                ),
            },
        )

    @classmethod
    def create(cls, node: BindingAttemptNode, store: StateStore) -> BindingMachine:
        machine = cls(node, store)
        machine._persist()
        return machine

    @classmethod
    def restore(cls, attempt_id: str, store: StateStore) -> BindingMachine:
        key = f"binding:{attempt_id}"
        snapshot = store.load(key)
        if snapshot is None:
            raise KeyError(key)
        if snapshot.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported binding snapshot schema")
        if snapshot.get("graph") != "binding":
            raise ValueError("binding snapshot graph is invalid")
        node = BindingAttemptNode.model_validate(snapshot.get("node"))
        if node.state.value != snapshot.get("state"):
            raise ValueError("binding snapshot state and node state disagree")
        machine = cls(node, store)
        machine.core.context["local_mode"] = bool(snapshot.get("local_mode", True))
        machine.core.context["occupancy_holder"] = str(
            snapshot.get("occupancy_holder") or ""
        )
        transitions = snapshot.get("transitions") or []
        if not isinstance(transitions, list):
            raise TypeError("binding transition log must be a list")
        cls._validate_transition_log(transitions, node.state)
        machine.core._log = list(transitions)
        return machine

    @staticmethod
    def _validate_transition_log(
        transitions: list, expected_state: BindingAttemptState
    ) -> None:
        graph = binding_graph()
        current = BindingAttemptState.CREATED
        for entry in transitions:
            if not isinstance(entry, dict):
                raise TypeError("binding transition entries must be objects")
            event = entry.get("event")
            result = graph.find_transition(current, event)
            if (
                result is None
                or entry.get("from") != current.value
                or entry.get("to") != result[1].value
            ):
                raise ValueError("binding transition log is not a valid graph path")
            current = result[1]
        if current is not expected_state:
            raise ValueError("binding transition log and node state disagree")


__all__ = [
    "BindingError",
    "BindingEvent",
    "BindingMachine",
    "TransitionError",
    "binding_graph",
]
