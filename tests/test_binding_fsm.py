import copy

import pytest
from pydantic import ValidationError

from datanode.fsm_core import MemoryStateStore, TransitionError
from datanode.models import (
    AgentRole,
    BindingAttemptNode,
    BindingAttemptState,
    BindingIntent,
)
from datanode.runtime_fsm.binding import BindingEvent, BindingMachine


def node(**changes):
    values = {
        "attempt_id": "bind-1",
        "tunnel_name": "dt-demo",
        "role": AgentRole.BULLET,
        "intent": BindingIntent.FREEZE,
        "holder": "tm_home",
        "previous_session_id": "ses_old",
    }
    values.update(changes)
    return BindingAttemptNode(**values)


def machine(*, previous="ses_old", role=AgentRole.BULLET):
    return BindingMachine.create(
        node(previous_session_id=previous, role=role), MemoryStateStore()
    )


def requested(**changes):
    values = {
        "holder": "tm_home",
        "local_mode": False,
        "occupancy_holder": "tm_home",
    }
    values.update(changes)
    return values


def proven(**changes):
    values = {
        "session_id": "ses_new",
        "tool": "opencode",
        "directory": "/workspace",
        "other_session_id": "ses_trigger",
        "rebuild": True,
        "endpoint_kind": "docker",
        "endpoint_server": "root@box",
        "endpoint_container": "agent",
        "endpoint_directory": "/workspace",
    }
    values.update(changes)
    return values


def test_happy_path_rebuild_bullet_requires_proof_before_commit():
    m = machine()
    m.send(BindingEvent.REQUESTED, requested())
    assert m.state is BindingAttemptState.PROVING
    m.send(BindingEvent.LIVE_SESSION_PROVEN, proven())
    assert m.state is BindingAttemptState.COMMITTING
    assert m.node.candidate_session_id == "ses_new"
    assert m.node.intent is BindingIntent.REBUILD
    m.send(BindingEvent.COMMIT_SUCCEEDED, {})
    assert m.state is BindingAttemptState.BOUND
    assert len(m.core.log) == 3


def test_missing_session_rejects_without_candidate():
    m = machine()
    m.send(BindingEvent.REQUESTED, requested())
    m.send(
        BindingEvent.LIVE_SESSION_MISSING,
        {"error": {"code": "missing", "message": "no opencode"}},
    )
    assert m.state is BindingAttemptState.REJECTED
    assert m.node.candidate_session_id == ""


def test_foreign_occupancy_guard_is_transactional():
    m = machine()
    m.send(BindingEvent.REQUESTED, requested(occupancy_holder="tm_other"))
    before = copy.deepcopy(m.store.load(m.key))
    with pytest.raises(TransitionError, match="guard rejected"):
        m.send(BindingEvent.LIVE_SESSION_PROVEN, proven())
    assert m.state is BindingAttemptState.PROVING
    assert m.node.candidate_session_id == ""
    assert m.store.load(m.key) == before


def test_same_session_as_other_role_is_rejected():
    m = machine()
    m.send(BindingEvent.REQUESTED, requested())
    with pytest.raises(TransitionError, match="guard rejected"):
        m.send(
            BindingEvent.LIVE_SESSION_PROVEN,
            proven(session_id="ses_trigger", other_session_id="ses_trigger"),
        )
    assert m.state is BindingAttemptState.PROVING


def test_rebuild_cannot_commit_the_previous_session():
    m = machine()
    m.send(BindingEvent.REQUESTED, requested())
    with pytest.raises(TransitionError, match="guard rejected"):
        m.send(
            BindingEvent.LIVE_SESSION_PROVEN,
            proven(session_id="ses_old", rebuild=True),
        )


def test_docker_bullet_requires_complete_endpoint():
    m = machine()
    m.send(BindingEvent.REQUESTED, requested())
    with pytest.raises(TransitionError, match="guard rejected"):
        m.send(
            BindingEvent.LIVE_SESSION_PROVEN,
            proven(endpoint_container=""),
        )


def test_local_mode_ignores_occupancy_holder():
    m = machine(role=AgentRole.TRIGGER)
    m.send(
        BindingEvent.REQUESTED,
        requested(local_mode=True, occupancy_holder="tm_other"),
    )
    m.send(
        BindingEvent.LIVE_SESSION_PROVEN,
        proven(
            rebuild=False,
            endpoint_kind="",
            other_session_id="",
        ),
    )
    m.send(BindingEvent.COMMIT_SUCCEEDED, {})
    assert m.state is BindingAttemptState.BOUND


def test_commit_failure_does_not_bind():
    m = machine()
    m.send(BindingEvent.REQUESTED, requested())
    m.send(BindingEvent.LIVE_SESSION_PROVEN, proven())
    m.send(
        BindingEvent.COMMIT_FAILED,
        {"error": {"code": "write_failed", "message": "disk"}},
    )
    assert m.state is BindingAttemptState.FAILED
    assert m.node.candidate_session_id == "ses_new"


def test_illegal_event_does_not_change_state():
    m = machine()
    with pytest.raises(ValidationError):
        m.send("unknown", {})
    with pytest.raises(TransitionError):
        m.send(BindingEvent.COMMIT_SUCCEEDED, {})
    assert m.state is BindingAttemptState.CREATED


def test_snapshot_round_trip():
    store = MemoryStateStore()
    m = BindingMachine.create(node(), store)
    m.send(BindingEvent.REQUESTED, requested())
    restored = BindingMachine.restore("bind-1", store)
    assert restored.state is BindingAttemptState.PROVING
    assert restored.core.log == m.core.log
