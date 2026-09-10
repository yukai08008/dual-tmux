from dual_tmux.binding import run_freeze_attempt
from dual_tmux.oc import empty_side


def _data():
    return {
        "name": "dt-demo",
        "op": "op_demo",
        "run": "run_demo",
        "trigger": {**empty_side(), "session_id": "ses_old"},
        "bullet": empty_side(),
        "runtime": {"server": "box", "directory": "/old"},
    }


def test_foreign_occupancy_does_not_run_body_or_mutate(monkeypatch):
    monkeypatch.setattr(
        "dual_tmux.binding.occupancy_context",
        lambda _name: ("tm_home", False, "tm_other"),
    )
    called = {"n": 0}

    def body(*_args):
        called["n"] += 1
        return True

    data = _data()
    assert run_freeze_attempt(data, "trigger", "op_demo", "auto", False, body=body) is False
    assert called["n"] == 0
    assert data["trigger"]["session_id"] == "ses_old"


def test_failed_body_restores_previous_binding(monkeypatch):
    monkeypatch.setattr(
        "dual_tmux.binding.occupancy_context",
        lambda _name: ("tm_home", True, ""),
    )

    def body(data, *_args):
        data["trigger"]["session_id"] = "ses_cleared"
        data["runtime"] = {"server": "new"}
        return False

    data = _data()
    assert run_freeze_attempt(data, "trigger", "op_demo", "auto", False, body=body) is False
    assert data["trigger"]["session_id"] == "ses_old"
    assert data["runtime"] == {"server": "box", "directory": "/old"}


def test_successful_rebuild_keeps_committed_session(monkeypatch):
    monkeypatch.setattr(
        "dual_tmux.binding.occupancy_context",
        lambda _name: ("tm_home", True, ""),
    )

    def body(data, *_args):
        data["trigger"]["session_id"] = "ses_new"
        data["trigger"]["directory"] = "/ops"
        return True

    data = _data()
    assert run_freeze_attempt(data, "trigger", "op_demo", "auto", False, body=body) is True
    assert data["trigger"]["session_id"] == "ses_new"
