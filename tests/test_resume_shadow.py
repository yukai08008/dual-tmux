import json

from datanode.runtime_fsm import ResumeState
from dual_tmux.resume_shadow import AtomicShadowStateStore, ResumeShadow


def tunnel():
    return {
        "name": "dt-shadow",
        "trigger": {"tool": "opencode", "session_id": "ses-trigger"},
        "bullet": {"tool": "opencode", "session_id": "ses-bullet"},
    }


def configure_shadow(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    monkeypatch.setenv("DT_CLIENT", "tm-shadow")
    monkeypatch.setattr(
        "dual_tmux.resume_shadow.existing_instance_id", lambda: "mac:shadow"
    )


def test_shadow_observes_success_without_performing_real_actions(tmp_path, monkeypatch):
    configure_shadow(tmp_path, monkeypatch)
    observer = ResumeShadow.start(tunnel())
    observer.preflight(tunnel(), {"safe": True})
    observer.ownership_acquired({"generation": 9, "newly_acquired": True})
    observer.restore_completed()
    observer.verification_passed(
        {
            "generation": 9,
            "writers": {
                "trigger": {"status": "ok", "count": 1, "pids": [10]},
                "bullet": {"status": "ok", "count": 1, "pids": [11]},
            },
        }
    )

    assert observer.machine.state is ResumeState.COMPLETED
    rows = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
    ]
    transitions = [row for row in rows if row["kind"].endswith("transition")]
    assert [row["state"] for row in transitions] == [
        "preflighting",
        "acquiring",
        "restoring",
        "verifying",
        "completed",
    ]
    assert not [row for row in rows if row["kind"].endswith("violation")]


def test_shadow_sink_failure_never_blocks_or_rolls_back_real_observation(
    tmp_path, monkeypatch
):
    configure_shadow(tmp_path, monkeypatch)
    observer = ResumeShadow.start(tunnel())
    monkeypatch.setattr(
        "dual_tmux.resume_shadow.event_log.emit",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("disk full")),
    )

    observer.preflight(tunnel(), {"safe": True})
    assert observer.machine.state is ResumeState.ACQUIRING


def test_shadow_tracks_verified_failure_and_proved_rollback(tmp_path, monkeypatch):
    configure_shadow(tmp_path, monkeypatch)
    observer = ResumeShadow.start(tunnel())
    observer.preflight(tunnel(), {"safe": True})
    observer.ownership_acquired({"generation": 12, "newly_acquired": True})
    observer.restore_completed()
    observer.verification_failed(SystemExit("duplicate writer"))
    observer.rollback_completed(parked=True, lease_released=True)

    assert observer.machine.state is ResumeState.FAILED
    assert observer.machine.node.error.code == "verification_failed"


def test_atomic_shadow_store_round_trip(tmp_path):
    store = AtomicShadowStateStore(tmp_path / "store")
    snapshot = {"state": "created", "node": {"attempt_id": "key"}}
    store.save("resume:key", snapshot)
    assert store.load("resume:key") == snapshot
    assert store.list_keys() == ["resume:key"]
    assert store.delete("resume:key") is True
