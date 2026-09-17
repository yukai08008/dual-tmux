import json

import pytest

from dual_tmux import activity, cli, log, recovery
from dual_tmux.store import save, tunnels_dir


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))


def _tunnel(**extra) -> dict:
    data = {
        "name": "dt-x",
        "op": "op_x",
        "run": "run_x",
        "trigger": {"tool": "opencode"},
        "bullet": {"tool": "opencode", "session_id": "ses_b1"},
        "runtime": {
            "server": "box",
            "container": "c1",
            "directory": "/workspace",
            "cmd": "ssh box",
        },
    }
    data.update(extra)
    return data


def _write_evidence(name: str, bullet_state: str, trigger_state: str = "idle") -> None:
    path = activity.evidence_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "name": name,
                "sampled_at": 1,
                "sides": {
                    "trigger": {"state": trigger_state, "sampled_at": 1},
                    "bullet": {"state": bullet_state, "sampled_at": 1},
                },
            }
        ),
        encoding="utf-8",
    )


def _failing_probe(_data):
    return {
        "healthy": False,
        "checked_at": "2026-09-16T10:00:00",
        "failures": ["transport"],
        "layers": {"transport": {"ok": False, "status": "unreachable"}},
    }


# --- auto_recover defaults on -------------------------------------------


def test_observe_treats_missing_auto_recover_as_enabled():
    calls = []
    data = _tunnel()  # no auto_recover key
    assert "auto_recover" not in data
    for now in (1, 2, 3):
        recovery.observe(
            data,
            now=now,
            prober=_failing_probe,
            recoverer=lambda _d: calls.append(1) or {"healthy": True},
        )
    assert calls == [1]


def test_observe_respects_explicit_disable():
    calls = []
    data = _tunnel(auto_recover=False)
    for now in (1, 2, 3, 4):
        recovery.observe(
            data,
            now=now,
            prober=_failing_probe,
            recoverer=lambda _d: calls.append(1) or {"healthy": True},
        )
    assert calls == []


def test_tunnel_node_defaults_auto_recover_on():
    from datanode.adapters import from_legacy_tunnel

    node = from_legacy_tunnel(_tunnel())
    assert node.auto_recover is True
    node_off = from_legacy_tunnel(_tunnel(auto_recover=False))
    assert node_off.auto_recover is False


def test_tick_gate_treats_missing_auto_recover_as_enabled():
    data = _tunnel()
    assert not data.get("auto_recover", True) is False
    assert _tunnel(auto_recover=False).get("auto_recover", True) is False


# --- auto_rebuild_if_stalled --------------------------------------------


class _FakeService:
    def __init__(self, error: Exception | None = None):
        self.calls = []
        self.error = error

    def rebuild(self, name, force=False):
        self.calls.append(name)
        if self.error:
            raise self.error
        return {"name": name}


def test_auto_rebuild_triggers_on_stalled_bullet():
    service = _FakeService()
    out = recovery.auto_rebuild_if_stalled(_tunnel(), service=service)
    assert out is None  # no evidence yet -> no action
    _write_evidence("dt-x", "stalled")
    out = recovery.auto_rebuild_if_stalled(_tunnel(), service=service)
    assert out is True
    assert service.calls == ["dt-x"]
    rows = log.read_events(limit=10, kind="recovery.rebuild")
    kinds = [r["kind"] for r in rows]
    assert "recovery.rebuild.auto" in kinds
    # counters hold until the bullet is observed working again
    state = recovery.read_state("dt-x")
    assert state["rebuild_attempts"] == 1
    assert state["rebuild_next_retry_at"] > 0


def test_auto_rebuild_backoff_between_attempts(monkeypatch):
    service = _FakeService()
    _write_evidence("dt-x", "stalled")
    recovery.auto_rebuild_if_stalled(_tunnel(), service=service)
    again = recovery.auto_rebuild_if_stalled(_tunnel(), service=service)
    assert again is None
    assert service.calls == ["dt-x"]  # not retried within the window


def test_auto_rebuild_caps_and_holds_at_attention():
    service = _FakeService()
    _write_evidence("dt-x", "stalled")
    state = recovery.read_state("dt-x")
    state.update(rebuild_attempts=3, rebuild_next_retry_at=0)
    recovery.save_state(state)
    out = recovery.auto_rebuild_if_stalled(_tunnel(), service=service)
    assert out is None
    assert service.calls == []
    state = recovery.read_state("dt-x")
    assert state["status"] == "attention"
    assert log.read_events(limit=10, kind="recovery.rebuild.hold")


def test_auto_rebuild_working_resets_counters_and_skips():
    service = _FakeService()
    _write_evidence("dt-x", "working")
    state = recovery.read_state("dt-x")
    state.update(rebuild_attempts=2, rebuild_next_retry_at=9999999999)
    recovery.save_state(state)
    assert recovery.auto_rebuild_if_stalled(_tunnel(), service=service) is None
    assert service.calls == []
    assert recovery.read_state("dt-x")["rebuild_attempts"] == 0


def test_auto_rebuild_disabled_or_idle_does_nothing():
    service = _FakeService()
    _write_evidence("dt-x", "stalled")
    assert recovery.auto_rebuild_if_stalled(_tunnel(auto_recover=False), service=service) is None
    _write_evidence("dt-x", "idle")
    assert recovery.auto_rebuild_if_stalled(_tunnel(), service=service) is None
    assert service.calls == []


def test_auto_rebuild_failure_keeps_backoff_and_emits():
    from dual_tmux.control import ControlError

    service = _FakeService(ControlError("missing_pane", "no pane", status=409))
    _write_evidence("dt-x", "stalled")
    out = recovery.auto_rebuild_if_stalled(_tunnel(), service=service)
    assert out is True
    rows = log.read_events(limit=10, kind="recovery.rebuild")
    assert any(r["kind"] == "recovery.rebuild.auto.fail" for r in rows)
    state = recovery.read_state("dt-x")
    assert state["rebuild_attempts"] == 1  # kept for backoff


# --- dt bullet recovery suggestion ---------------------------------------


def _bullet_env(monkeypatch, bullet_state, trigger_runtime, pane_cmd="ssh"):
    data = _tunnel()
    save(tunnels_dir() / "dt-x.json", data)
    path = activity.evidence_path("dt-x")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "name": "dt-x",
                "sampled_at": 1,
                "sides": {
                    "trigger": {"state": "idle", "runtime": trigger_runtime, "sampled_at": 1},
                    "bullet": {"state": bullet_state, "runtime": "transport", "sampled_at": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _pane: pane_cmd)
    monkeypatch.setattr(
        "dual_tmux.recovery.remote_session_pids", lambda _data: [101]
    )
    return data


def test_bullet_recovery_suggests_resume_when_trigger_down(monkeypatch):
    _bullet_env(monkeypatch, "stalled", "down")
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["recovery"] == "dt resume"


def test_bullet_recovery_suggests_rebuild_when_trigger_alive(monkeypatch):
    _bullet_env(monkeypatch, "stalled", "agent")
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["hint"].startswith("stalled_no_progress_")
    assert snap["recovery"] == "dt rebuild"


def test_bullet_recovery_empty_when_healthy(monkeypatch):
    _bullet_env(monkeypatch, "idle", "agent")
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["recovery"] == ""


# --- registry -------------------------------------------------------------


def test_kind_meta_covers_auto_rebuild_events():
    for kind in (
        "recovery.rebuild.auto",
        "recovery.rebuild.auto.fail",
        "recovery.rebuild.hold",
    ):
        assert log.meta(kind)["cat"] == "system"
        assert log.meta(kind)["label"]
    assert log.meta("recovery.rebuild.hold")["sev"] == "warn"
    assert log.meta("recovery.rebuild.auto.fail")["sev"] == "error"


# --- recovery drop suppression: warm-up + active turn --------------------


def _stamp_resume(data, epoch):
    from datetime import datetime, timezone

    stamp = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()
    data.setdefault("times", {})["resume_at"] = stamp.isoformat()
    return data


def _write_turn_evidence(name, *, state="idle", sampled_at=0, last_change=0):
    path = activity.evidence_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    side = {"state": state, "sampled_at": sampled_at}
    if last_change:
        side["last_semantic_change_at"] = last_change
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "name": name,
                "sampled_at": sampled_at,
                "sides": {
                    "trigger": side,
                    "bullet": {"state": "idle", "sampled_at": sampled_at},
                },
            }
        ),
        encoding="utf-8",
    )


def _write_synced_tick(source, data, epoch, fp="fp1"):
    path = activity.persist_ticks_path(source, data["op"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{epoch} 2026-09-17T18:00:00 {data['name']} opencode ssh {fp}\n",
        encoding="utf-8",
    )


def test_incident_repro_resume_then_false_negatives_and_active_turn(tmp_path, monkeypatch):
    """IS-260917185420 repro: resume, 4 probe failures within the warm-up
    window while the user starts a turn — recovery must neither fire the
    occupancy-stealing resume nor produce a dt.drop."""
    monkeypatch.setenv("OPENCODE_SESSIONS", str(tmp_path / "sessions"))
    calls = []
    data = _stamp_resume(_tunnel(), 1000)
    _write_turn_evidence(
        "dt-x", state="working", sampled_at=1020, last_change=1015
    )  # trigger.turn.start at 18:15:53-style moment
    for now in (1022, 1030, 1045, 1058):  # four false negatives after resume
        state = recovery.observe(
            data,
            now=now,
            prober=_failing_probe,
            recoverer=lambda _d: calls.append(1) or {"healthy": True},
        )
    assert calls == []
    assert state["consecutive_failures"] == 0
    assert state["status"] == "suspect"
    assert log.read_events(limit=20, kind="dt.drop") == []
    assert log.read_events(limit=20, kind="recovery.drop.suppressed") == []


def test_warmup_expiry_resumes_failure_counting(monkeypatch):
    calls = []
    data = _stamp_resume(_tunnel(), 1000)
    for now in (1010, 1030, 1050):
        recovery.observe(
            data,
            now=now,
            prober=_failing_probe,
            recoverer=lambda _d: calls.append(1) or {"healthy": True},
        )
    assert recovery.read_state("dt-x")["consecutive_failures"] == 0
    for now in (1061, 1062, 1063):  # warm-up over, counting resumes
        state = recovery.observe(
            data,
            now=now,
            prober=_failing_probe,
            recoverer=lambda _d: calls.append(1) or {"healthy": True},
        )
    assert len(calls) == 1
    assert state["status"] == "healthy"


def test_active_turn_suppresses_recovery_and_emits_event(monkeypatch):
    calls = []
    data = _tunnel()
    state = recovery.read_state("dt-x")
    state.update(consecutive_failures=2, next_retry_at=0)
    recovery.save_state(state)
    _write_turn_evidence(
        "dt-x", state="working", sampled_at=2990, last_change=2985
    )
    state = recovery.observe(
        data,
        now=3000,
        prober=_failing_probe,
        recoverer=lambda _d: calls.append(1) or {"healthy": True},
    )
    assert calls == []  # third failure reached the threshold but turn is live
    assert state["status"] == "degraded"
    assert state["next_retry_at"] == 3000 + recovery.RECOVERY_TURN_RECHECK_SECONDS
    rows = log.read_events(limit=20, kind="recovery.drop.suppressed")
    assert rows and rows[0]["reason"] == "active_turn"
    assert rows[0]["consecutive_failures"] == 3
    assert log.read_events(limit=20, kind="dt.drop") == []


def test_recent_turn_end_via_synced_ticks_suppresses(tmp_path, monkeypatch):
    """Cross-client visibility: the holder's fingerprint change synced
    through the hub suppresses the steal even with no local evidence."""
    root = tmp_path / "persist"
    monkeypatch.setattr("dual_tmux.oc.persist_root", lambda: root)
    calls = []
    data = _tunnel()
    state = recovery.read_state("dt-x")
    state.update(consecutive_failures=2, next_retry_at=0)
    recovery.save_state(state)
    _write_synced_tick("tm_other", data, 2970)
    state = recovery.observe(
        data,
        now=3000,
        prober=_failing_probe,
        recoverer=lambda _d: calls.append(1) or {"healthy": True},
    )
    assert calls == []
    assert log.read_events(limit=20, kind="recovery.drop.suppressed")


def test_quiet_turn_after_window_recovers(monkeypatch):
    """Positive path: once the turn has been quiet past the window and the
    threshold holds, recovery fires as before (real trigger_agent death)."""
    calls = []
    data = _tunnel()
    state = recovery.read_state("dt-x")
    state.update(consecutive_failures=2, next_retry_at=0)
    recovery.save_state(state)
    _write_turn_evidence("dt-x", state="idle", sampled_at=2600, last_change=2600)
    state = recovery.observe(
        data,
        now=2600 + recovery.RECOVERY_TURN_WINDOW_SECONDS + 1,
        prober=_failing_probe,
        recoverer=lambda _d: calls.append(1) or {"healthy": True},
    )
    assert calls == [1]
    assert state["status"] == "healthy"
    assert log.read_events(limit=20, kind="recovery.drop.suppressed") == []


def test_missing_activity_evidence_fails_open(monkeypatch):
    calls = []
    data = _tunnel()
    for now in (1, 2, 3):
        state = recovery.observe(
            data,
            now=now,
            prober=_failing_probe,
            recoverer=lambda _d: calls.append(1) or {"healthy": True},
        )
    assert len(calls) == 1
    assert state["status"] == "healthy"
