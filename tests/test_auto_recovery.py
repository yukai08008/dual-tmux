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
