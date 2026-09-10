import json

import pytest
from pydantic import ValidationError

from datanode.fsm_core import TransitionError
from datanode.runtime_fsm import ResumeState
from dual_tmux.resume_attempt import AtomicResumeStateStore, ResumeAttempt


def tunnel():
    return {
        "name": "dt-shadow",
        "trigger": {"tool": "opencode", "session_id": "ses-trigger"},
        "bullet": {"tool": "opencode", "session_id": "ses-bullet"},
    }


def configure_attempt(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    monkeypatch.setenv("DT_CLIENT", "tm-shadow")
    monkeypatch.setattr(
        "dual_tmux.resume_attempt.existing_instance_id", lambda: "mac:shadow"
    )


def test_attempt_records_success_and_blocks_on_illegal_transition(tmp_path, monkeypatch):
    configure_attempt(tmp_path, monkeypatch)
    attempt = ResumeAttempt.start(tunnel())
    attempt.preflight(tunnel(), {"safe": True})
    attempt.ownership_acquired({"generation": 9, "newly_acquired": True})
    attempt.restore_completed()
    attempt.verification_passed(
        {
            "generation": 9,
            "holder": "tm-shadow",
            "writers": {},
        }
    )

    assert attempt.machine.state is ResumeState.COMPLETED
    rows = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    transitions = [row for row in rows if row["kind"].endswith("transition")]
    assert [row["state"] for row in transitions] == [
        "preflighting",
        "acquiring",
        "restoring",
        "verifying",
        "completed",
    ]
    snapshots = list((tmp_path / "fsm" / "resume").glob("*.json"))
    assert len(snapshots) == 1
    assert json.loads(snapshots[0].read_text())["state"] == "completed"
    with pytest.raises((TransitionError, ValidationError)):
        attempt.restore_completed()


def test_event_log_failure_does_not_block_transition(tmp_path, monkeypatch):
    configure_attempt(tmp_path, monkeypatch)
    attempt = ResumeAttempt.start(tunnel())
    monkeypatch.setattr(
        "dual_tmux.resume_attempt.event_log.emit",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("disk full")),
    )

    attempt.preflight(tunnel(), {"safe": True})
    assert attempt.machine.state is ResumeState.ACQUIRING


def test_attempt_tracks_verified_failure_and_keeps_occupancy(tmp_path, monkeypatch):
    configure_attempt(tmp_path, monkeypatch)
    attempt = ResumeAttempt.start(tunnel())
    attempt.preflight(tunnel(), {"safe": True})
    attempt.ownership_acquired({"generation": 12, "newly_acquired": True})
    attempt.restore_completed()
    attempt.verification_failed(SystemExit("duplicate writer"))
    attempt.keep_occupancy_after_failure()

    assert attempt.machine.state is ResumeState.ATTENTION
    assert attempt.machine.node.error.code == "rollback_uncertain"


def test_atomic_resume_store_round_trip(tmp_path):
    store = AtomicResumeStateStore(tmp_path / "store")
    snapshot = {"state": "created", "node": {"attempt_id": "key"}}
    store.save("resume:key", snapshot)
    assert store.load("resume:key") == snapshot
    assert store.list_keys() == ["resume:key"]
    assert store.delete("resume:key") is True
