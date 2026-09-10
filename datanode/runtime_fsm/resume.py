"""Pure, persisted ResumeAttempt FSM.

This module deliberately performs no tmux, SSH, snapshot or Hub I/O. External
workers perform an action and report its validated result as an event. Guards
stay side-effect free. ControlService.resume is the worker: it may not claim
occupancy or restore tmux unless the matching event is accepted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from datanode.fsm_core import Graph, Machine, StateStore, TransitionError

SCHEMA_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResumeState(str, Enum):
    CREATED = "created"
    PREFLIGHTING = "preflighting"
    ACQUIRING = "acquiring"
    RESTORING = "restoring"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ROLLING_BACK = "rolling_back"
    FAILED = "failed"
    ATTENTION = "attention"


class ResumeEvent(str, Enum):
    PROCESSING_STARTED = "processing_started"
    PREFLIGHT_PASSED = "preflight_passed"
    PREFLIGHT_REJECTED = "preflight_rejected"
    OWNERSHIP_ACQUIRED = "ownership_acquired"
    OWNERSHIP_FAILED = "ownership_failed"
    RESTORE_COMPLETED = "restore_completed"
    RESTORE_FAILED = "restore_failed"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    ROLLBACK_COMPLETED = "rollback_completed"
    ROLLBACK_UNCERTAIN = "rollback_uncertain"


class ResumeError(StrictModel):
    code: str = Field(min_length=1)
    message: str = ""
    stage: str = ""
    side: Literal["", "trigger", "bullet"] = ""


class OccupancyToken(StrictModel):
    tunnel_name: str = Field(pattern=r"^dt-")
    holder_client_id: str = Field(min_length=1)
    generation: int = Field(ge=0)
    newly_acquired: bool = False
    holder_instance_id: str = ""
    lease_revision: str = ""


OwnershipToken = OccupancyToken


class VerificationEvidence(StrictModel):
    generation: int = Field(ge=0)
    occupancy_holder: str = ""
    trigger_writer_count: int = Field(ge=0)
    bullet_writer_count: int = Field(ge=0)
    trigger_observation_id: str = Field(min_length=1)
    bullet_observation_id: str = Field(min_length=1)


class ResumeAttemptNode(StrictModel):
    attempt_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    tunnel_name: str = Field(pattern=r"^dt-")
    claimant_client_id: str = Field(min_length=1)
    claimant_instance_id: str = Field(min_length=1)
    state: ResumeState = ResumeState.CREATED
    expected_binding_revisions: tuple[str, ...] = ()
    ownership_token: OwnershipToken | None = None
    transfer_ids: tuple[str, ...] = Field(default=(), max_length=2)
    verification: VerificationEvidence | None = None
    error: ResumeError | None = None
    rollback_evidence: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @model_validator(mode="after")
    def legal_state_facts(self) -> ResumeAttemptNode:
        needs_ownership = {
            ResumeState.RESTORING,
            ResumeState.VERIFYING,
            ResumeState.COMPLETED,
            ResumeState.ROLLING_BACK,
        }
        if self.state in needs_ownership and self.ownership_token is None:
            raise ValueError(f"state {self.state.value} requires an ownership token")
        if self.ownership_token is not None:
            if self.ownership_token.tunnel_name != self.tunnel_name:
                raise ValueError("ownership token belongs to a different tunnel")
            if self.ownership_token.holder_client_id != self.claimant_client_id:
                raise ValueError("ownership token belongs to a different client")
            if (
                self.ownership_token.holder_instance_id
                and self.ownership_token.holder_instance_id != self.claimant_instance_id
            ):
                raise ValueError("ownership token belongs to a different installation")
        if self.state is ResumeState.COMPLETED:
            verification = self.verification
            ownership_token = self.ownership_token
            if verification is None:
                raise ValueError("completed resume requires verification evidence")
            if ownership_token is None:
                raise ValueError("completed resume requires an ownership token")
            if verification.generation != ownership_token.generation:
                raise ValueError("verification generation differs from ownership token")
            if (
                verification.occupancy_holder
                and verification.occupancy_holder != self.claimant_client_id
            ):
                raise ValueError("verification occupancy holder differs from claimant")
            if (
                verification.trigger_writer_count > 1
                or verification.bullet_writer_count > 1
            ):
                raise ValueError("completed resume cannot have multiple writers per role")
        if (
            self.state
            in {ResumeState.REJECTED, ResumeState.FAILED, ResumeState.ATTENTION}
            and not self.error
        ):
            raise ValueError(f"state {self.state.value} requires an error")
        if len(set(self.transfer_ids)) != len(self.transfer_ids):
            raise ValueError("transfer IDs must be unique")
        return self


class ProcessingStarted(StrictModel):
    event: Literal[ResumeEvent.PROCESSING_STARTED] = ResumeEvent.PROCESSING_STARTED


class PreflightPassed(StrictModel):
    event: Literal[ResumeEvent.PREFLIGHT_PASSED] = ResumeEvent.PREFLIGHT_PASSED
    binding_revisions: tuple[str, ...]
    revisions_stable: bool


class PreflightRejected(StrictModel):
    event: Literal[ResumeEvent.PREFLIGHT_REJECTED] = ResumeEvent.PREFLIGHT_REJECTED
    error: ResumeError


class OwnershipAcquired(StrictModel):
    event: Literal[ResumeEvent.OWNERSHIP_ACQUIRED] = ResumeEvent.OWNERSHIP_ACQUIRED
    token: OwnershipToken


class OwnershipFailed(StrictModel):
    event: Literal[ResumeEvent.OWNERSHIP_FAILED] = ResumeEvent.OWNERSHIP_FAILED
    error: ResumeError


class RestoreCompleted(StrictModel):
    event: Literal[ResumeEvent.RESTORE_COMPLETED] = ResumeEvent.RESTORE_COMPLETED
    transfer_ids: tuple[str, ...] = Field(default=(), max_length=2)


class RestoreFailed(StrictModel):
    event: Literal[ResumeEvent.RESTORE_FAILED] = ResumeEvent.RESTORE_FAILED
    error: ResumeError


class VerificationPassed(StrictModel):
    event: Literal[ResumeEvent.VERIFICATION_PASSED] = ResumeEvent.VERIFICATION_PASSED
    evidence: VerificationEvidence


class VerificationFailed(StrictModel):
    event: Literal[ResumeEvent.VERIFICATION_FAILED] = ResumeEvent.VERIFICATION_FAILED
    error: ResumeError


class RollbackCompleted(StrictModel):
    event: Literal[ResumeEvent.ROLLBACK_COMPLETED] = ResumeEvent.ROLLBACK_COMPLETED
    evidence: tuple[str, ...] = Field(min_length=1)
    panes_parked: bool
    lease_released: bool


class RollbackUncertain(StrictModel):
    event: Literal[ResumeEvent.ROLLBACK_UNCERTAIN] = ResumeEvent.ROLLBACK_UNCERTAIN
    error: ResumeError


ResumeEventPayload = Annotated[
    ProcessingStarted
    | PreflightPassed
    | PreflightRejected
    | OwnershipAcquired
    | OwnershipFailed
    | RestoreCompleted
    | RestoreFailed
    | VerificationPassed
    | VerificationFailed
    | RollbackCompleted
    | RollbackUncertain,
    Field(discriminator="event"),
]
PAYLOAD_ADAPTER = TypeAdapter(ResumeEventPayload)


def _payload(context: dict) -> ResumeEventPayload:
    return context["payload"]


def _preflight_stable(context: dict) -> bool:
    payload = _payload(context)
    return isinstance(payload, PreflightPassed) and payload.revisions_stable


def _token_matches_claimant(context: dict) -> bool:
    payload = _payload(context)
    node: ResumeAttemptNode = context["node"]
    return bool(
        isinstance(payload, OwnershipAcquired)
        and payload.token.tunnel_name == node.tunnel_name
        and payload.token.holder_client_id == node.claimant_client_id
        and (
            not payload.token.holder_instance_id
            or payload.token.holder_instance_id == node.claimant_instance_id
        )
    )


def _verification_matches_occupancy(context: dict) -> bool:
    payload = _payload(context)
    node: ResumeAttemptNode = context["node"]
    if not isinstance(payload, VerificationPassed) or node.ownership_token is None:
        return False
    evidence = payload.evidence
    if evidence.generation != node.ownership_token.generation:
        return False
    if evidence.trigger_writer_count > 1 or evidence.bullet_writer_count > 1:
        return False
    return (
        not evidence.occupancy_holder
        or evidence.occupancy_holder == node.claimant_client_id
    )


def _rollback_proved(context: dict) -> bool:
    payload = _payload(context)
    node: ResumeAttemptNode = context["node"]
    if not isinstance(payload, RollbackCompleted) or not payload.panes_parked:
        return False
    if node.ownership_token and node.ownership_token.newly_acquired:
        return payload.lease_released
    return True


def _enter(target: ResumeState):
    def update(context: dict) -> None:
        node: ResumeAttemptNode = context["node"]
        payload = _payload(context)
        changes: dict = {"state": target, "updated_at": _now()}
        if isinstance(payload, PreflightPassed):
            changes["expected_binding_revisions"] = payload.binding_revisions
            changes["error"] = None
        elif isinstance(payload, (PreflightRejected, OwnershipFailed)):
            changes["error"] = payload.error
        elif isinstance(payload, OwnershipAcquired):
            changes["ownership_token"] = payload.token
            changes["error"] = None
        elif isinstance(payload, RestoreCompleted):
            changes["transfer_ids"] = payload.transfer_ids
        elif isinstance(
            payload, (RestoreFailed, VerificationFailed, RollbackUncertain)
        ):
            changes["error"] = payload.error
        elif isinstance(payload, VerificationPassed):
            changes["verification"] = payload.evidence
            changes["error"] = None
        elif isinstance(payload, RollbackCompleted):
            changes["rollback_evidence"] = payload.evidence
        context["node"] = ResumeAttemptNode.model_validate(
            node.model_copy(update=changes).model_dump()
        )

    return update


def resume_graph() -> Graph:
    event = ResumeEvent
    state = ResumeState
    return Graph(
        {
            (state.CREATED, state.PREFLIGHTING): {
                "event": event.PROCESSING_STARTED.value,
                "on_enter": _enter(state.PREFLIGHTING),
            },
            (state.PREFLIGHTING, state.ACQUIRING): {
                "event": event.PREFLIGHT_PASSED.value,
                "guard": _preflight_stable,
                "on_enter": _enter(state.ACQUIRING),
            },
            (state.PREFLIGHTING, state.REJECTED): {
                "event": event.PREFLIGHT_REJECTED.value,
                "on_enter": _enter(state.REJECTED),
            },
            (state.ACQUIRING, state.RESTORING): {
                "event": event.OWNERSHIP_ACQUIRED.value,
                "guard": _token_matches_claimant,
                "on_enter": _enter(state.RESTORING),
            },
            (state.ACQUIRING, state.FAILED): {
                "event": event.OWNERSHIP_FAILED.value,
                "on_enter": _enter(state.FAILED),
            },
            (state.RESTORING, state.VERIFYING): {
                "event": event.RESTORE_COMPLETED.value,
                "on_enter": _enter(state.VERIFYING),
            },
            (state.RESTORING, state.ROLLING_BACK): {
                "event": event.RESTORE_FAILED.value,
                "on_enter": _enter(state.ROLLING_BACK),
            },
            (state.VERIFYING, state.COMPLETED): {
                "event": event.VERIFICATION_PASSED.value,
                "guard": _verification_matches_occupancy,
                "on_enter": _enter(state.COMPLETED),
            },
            (state.VERIFYING, state.ROLLING_BACK): {
                "event": event.VERIFICATION_FAILED.value,
                "on_enter": _enter(state.ROLLING_BACK),
            },
            (state.ROLLING_BACK, state.FAILED): {
                "event": event.ROLLBACK_COMPLETED.value,
                "guard": _rollback_proved,
                "on_enter": _enter(state.FAILED),
            },
            (state.ROLLING_BACK, state.ATTENTION): {
                "event": event.ROLLBACK_UNCERTAIN.value,
                "on_enter": _enter(state.ATTENTION),
            },
        },
        initial=state.CREATED,
    )


class ResumeMachine:
    """Typed wrapper that persists every successful pure state transition."""

    def __init__(self, node: ResumeAttemptNode, store: StateStore):
        self.store = store
        self.core = Machine(resume_graph(), context={"node": node})
        self.core.state = node.state

    @property
    def node(self) -> ResumeAttemptNode:
        return self.core.context["node"]

    @property
    def state(self) -> ResumeState:
        return self.core.state

    @property
    def key(self) -> str:
        return f"resume:{self.node.attempt_id}"

    def send(
        self, event: ResumeEvent | str, payload: dict | StrictModel
    ) -> ResumeState:
        event_name = event.value if isinstance(event, ResumeEvent) else str(event)
        raw = (
            payload.model_dump(mode="json")
            if isinstance(payload, BaseModel)
            else payload
        )
        value = PAYLOAD_ADAPTER.validate_python({**raw, "event": event_name})
        before_state = self.core.state
        before_node = self.node
        before_log = self.core.log
        prior_payload = self.core.context.get("payload")
        self.core.context["payload"] = value
        try:
            result = self.core.send(event_name)
            self._persist()
        except Exception:
            self.core.state = before_state
            self.core.context["node"] = before_node
            self.core._log = before_log
            if prior_payload is None:
                self.core.context.pop("payload", None)
            else:
                self.core.context["payload"] = prior_payload
            raise
        return ResumeState(result.value)

    def _persist(self) -> None:
        self.store.save(
            self.key,
            {
                "schema_version": SCHEMA_VERSION,
                "graph": "resume",
                "state": self.state.value,
                "node": self.node.model_dump(mode="json"),
                "transitions": self.core.log,
            },
        )

    @classmethod
    def create(cls, node: ResumeAttemptNode, store: StateStore) -> ResumeMachine:
        machine = cls(node, store)
        machine._persist()
        return machine

    @classmethod
    def restore(cls, attempt_id: str, store: StateStore) -> ResumeMachine:
        key = f"resume:{attempt_id}"
        snapshot = store.load(key)
        if snapshot is None:
            raise KeyError(key)
        if snapshot.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported resume snapshot schema")
        if snapshot.get("graph") != "resume":
            raise ValueError("resume snapshot graph is invalid")
        node = ResumeAttemptNode.model_validate(snapshot.get("node"))
        if node.state.value != snapshot.get("state"):
            raise ValueError("resume snapshot state and node state disagree")
        machine = cls(node, store)
        transitions = snapshot.get("transitions") or []
        if not isinstance(transitions, list):
            raise TypeError("resume transition log must be a list")
        cls._validate_transition_log(transitions, node.state)
        machine.core._log = list(transitions)
        return machine

    @staticmethod
    def _validate_transition_log(
        transitions: list, expected_state: ResumeState
    ) -> None:
        graph = resume_graph()
        current = ResumeState.CREATED
        for entry in transitions:
            if not isinstance(entry, dict):
                raise TypeError("resume transition entries must be objects")
            event = entry.get("event")
            result = graph.find_transition(current, event)
            if (
                result is None
                or entry.get("from") != current.value
                or entry.get("to") != result[1].value
            ):
                raise ValueError("resume transition log is not a valid graph path")
            current = result[1]
        if current is not expected_state:
            raise ValueError("resume transition log and node state disagree")


__all__ = [
    "OccupancyToken",
    "OwnershipToken",
    "ResumeAttemptNode",
    "ResumeError",
    "ResumeEvent",
    "ResumeMachine",
    "ResumeState",
    "TransitionError",
    "VerificationEvidence",
    "resume_graph",
]
