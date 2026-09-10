import copy

import pytest
from pydantic import ValidationError

from datanode.fsm_core import MemoryStateStore, TransitionError
from datanode.runtime_fsm import (
    OwnershipToken,
    ResumeAttemptNode,
    ResumeEvent,
    ResumeMachine,
    ResumeState,
)


def node(**changes):
    values = {
        "attempt_id": "resume-1",
        "idempotency_key": "idem-1",
        "tunnel_name": "dt-demo",
        "claimant_client_id": "tm-home",
        "claimant_instance_id": "mac:one",
    }
    values.update(changes)
    return ResumeAttemptNode(**values)


def error(code="failed"):
    return {"code": code, "message": "test failure"}


def token(**changes):
    values = {
        "tunnel_name": "dt-demo",
        "holder_client_id": "tm-home",
        "holder_instance_id": "mac:one",
        "generation": 8,
        "lease_revision": "lease:8",
        "newly_acquired": True,
    }
    values.update(changes)
    return values


def verification(**changes):
    values = {
        "generation": 8,
        "trigger_writer_count": 1,
        "bullet_writer_count": 1,
        "trigger_observation_id": "pane:trigger:8",
        "bullet_observation_id": "pane:bullet:8",
    }
    values.update(changes)
    return values


def machine_at_acquiring():
    machine = ResumeMachine.create(node(), MemoryStateStore())
    machine.send(ResumeEvent.PROCESSING_STARTED, {})
    machine.send(
        ResumeEvent.PREFLIGHT_PASSED,
        {"binding_revisions": ["trigger:4", "bullet:7"], "revisions_stable": True},
    )
    return machine


def machine_at_restoring(*, newly_acquired=True):
    machine = machine_at_acquiring()
    machine.send(
        ResumeEvent.OWNERSHIP_ACQUIRED,
        {"token": token(newly_acquired=newly_acquired)},
    )
    return machine


def test_happy_path_requires_occupancy_before_restore():
    machine = machine_at_restoring()
    assert machine.node.ownership_token.generation == 8
    machine.send(
        ResumeEvent.RESTORE_COMPLETED,
        {"transfer_ids": ["transfer-trigger", "transfer-bullet"]},
    )
    machine.send(ResumeEvent.VERIFICATION_PASSED, {"evidence": verification()})

    assert machine.state is ResumeState.COMPLETED
    assert machine.node.transfer_ids == ("transfer-trigger", "transfer-bullet")
    assert len(machine.core.log) == 5


def test_unstable_preflight_guard_is_transactional():
    store = MemoryStateStore()
    machine = ResumeMachine.create(node(), store)
    machine.send(ResumeEvent.PROCESSING_STARTED, {})
    before = copy.deepcopy(store.load(machine.key))

    with pytest.raises(TransitionError, match="guard rejected"):
        machine.send(
            ResumeEvent.PREFLIGHT_PASSED,
            {"binding_revisions": ["trigger:4"], "revisions_stable": False},
        )

    assert machine.state is ResumeState.PREFLIGHTING
    assert machine.node.expected_binding_revisions == ()
    assert store.load(machine.key) == before


@pytest.mark.parametrize(
    "bad_token",
    [
        token(tunnel_name="dt-other"),
        token(holder_client_id="tm-other"),
        token(holder_instance_id="mac:other"),
    ],
)
def test_ownership_token_must_match_claimant(bad_token):
    machine = machine_at_acquiring()
    with pytest.raises(TransitionError, match="guard rejected"):
        machine.send(ResumeEvent.OWNERSHIP_ACQUIRED, {"token": bad_token})
    assert machine.state is ResumeState.ACQUIRING
    assert machine.node.ownership_token is None


def test_preflight_rejection_and_ownership_failure_are_safe_terminal_states():
    rejected = ResumeMachine.create(node(), MemoryStateStore())
    rejected.send(ResumeEvent.PROCESSING_STARTED, {})
    rejected.send(ResumeEvent.PREFLIGHT_REJECTED, {"error": error("conflict")})
    assert rejected.state is ResumeState.REJECTED
    assert rejected.node.ownership_token is None

    failed = machine_at_acquiring()
    failed.send(ResumeEvent.OWNERSHIP_FAILED, {"error": error("lease_busy")})
    assert failed.state is ResumeState.FAILED
    assert failed.node.ownership_token is None


def test_new_lease_rollback_requires_park_and_release_evidence():
    machine = machine_at_restoring(newly_acquired=True)
    machine.send(ResumeEvent.RESTORE_FAILED, {"error": error("import_failed")})
    assert machine.state is ResumeState.ROLLING_BACK

    with pytest.raises(TransitionError, match="guard rejected"):
        machine.send(
            ResumeEvent.ROLLBACK_COMPLETED,
            {"evidence": ["park:1"], "panes_parked": True, "lease_released": False},
        )
    assert machine.state is ResumeState.ROLLING_BACK

    machine.send(
        ResumeEvent.ROLLBACK_COMPLETED,
        {
            "evidence": ["park:1", "release:8"],
            "panes_parked": True,
            "lease_released": True,
        },
    )
    assert machine.state is ResumeState.FAILED


def test_uncertain_rollback_requires_attention():
    machine = machine_at_restoring()
    machine.send(ResumeEvent.RESTORE_FAILED, {"error": error("restore_failed")})
    machine.send(
        ResumeEvent.ROLLBACK_UNCERTAIN,
        {"error": error("release_result_unknown")},
    )
    assert machine.state is ResumeState.ATTENTION


@pytest.mark.parametrize(
    "evidence",
    [
        verification(generation=7),
        verification(trigger_writer_count=2),
        verification(bullet_writer_count=2),
        verification(occupancy_holder="tm-other"),
    ],
)
def test_verification_rejects_stale_generation_split_brain_or_foreign_holder(evidence):
    machine = machine_at_restoring()
    machine.send(ResumeEvent.RESTORE_COMPLETED, {})
    with pytest.raises(TransitionError, match="guard rejected"):
        machine.send(ResumeEvent.VERIFICATION_PASSED, {"evidence": evidence})
    assert machine.state is ResumeState.VERIFYING


def test_verification_allows_unprobed_writers_when_occupancy_matches():
    machine = machine_at_restoring()
    machine.send(ResumeEvent.RESTORE_COMPLETED, {})
    machine.send(
        ResumeEvent.VERIFICATION_PASSED,
        {
            "evidence": verification(
                trigger_writer_count=0,
                bullet_writer_count=0,
                occupancy_holder="tm-home",
            )
        },
    )
    assert machine.state is ResumeState.COMPLETED


def test_snapshot_round_trip_and_corruption_detection():
    store = MemoryStateStore()
    machine = ResumeMachine.create(node(), store)
    machine.send(ResumeEvent.PROCESSING_STARTED, {})
    restored = ResumeMachine.restore("resume-1", store)
    assert restored.state is ResumeState.PREFLIGHTING
    assert restored.core.log == machine.core.log

    valid_snapshot = store.load(machine.key)
    bad_state = copy.deepcopy(valid_snapshot)
    bad_state["state"] = "completed"
    store.save(machine.key, bad_state)
    with pytest.raises(ValueError, match="disagree"):
        ResumeMachine.restore("resume-1", store)

    bad_log = copy.deepcopy(valid_snapshot)
    bad_log["transitions"][0]["to"] = "completed"
    machine.store.save(machine.key, bad_log)
    with pytest.raises(ValueError, match="valid graph path"):
        ResumeMachine.restore("resume-1", machine.store)


def test_payload_and_node_constraints_are_explicit():
    machine = ResumeMachine.create(node(), MemoryStateStore())
    with pytest.raises(ValidationError):
        machine.send("unknown", {})
    with pytest.raises(ValidationError, match="too_long"):
        ResumeAttemptNode(
            **node().model_dump(exclude={"transfer_ids"}),
            transfer_ids=("one", "two", "three"),
        )
    with pytest.raises(ValidationError, match="different tunnel"):
        node(ownership_token=OwnershipToken(**token(tunnel_name="dt-other")))
    with pytest.raises(ValidationError, match="unique"):
        node(transfer_ids=("same", "same"))
