from datanode.adapters import from_legacy_tunnel
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
    persisted = []
    monkeypatch.setattr(
        "dual_tmux.binding.persist_run_entry",
        lambda *args: persisted.append(args),
    )

    def body(data, *_args):
        data["trigger"]["session_id"] = "ses_cleared"
        data["runtime"] = {"server": "new"}
        return False

    data = _data()
    assert run_freeze_attempt(data, "trigger", "op_demo", "auto", False, body=body) is False
    assert data["trigger"]["session_id"] == "ses_old"
    assert data["runtime"] == {"server": "box", "directory": "/old"}
    assert persisted == []


def test_successful_rebuild_keeps_committed_session(monkeypatch):
    monkeypatch.setattr(
        "dual_tmux.binding.occupancy_context",
        lambda _name: ("tm_home", True, ""),
    )
    persisted = []
    monkeypatch.setattr(
        "dual_tmux.binding.persist_run_entry",
        lambda *args: persisted.append(args),
    )

    def body(data, *_args):
        data["trigger"]["session_id"] = "ses_new"
        data["trigger"]["directory"] = "/ops"
        return True

    data = _data()
    assert run_freeze_attempt(data, "trigger", "op_demo", "auto", False, body=body) is True
    assert data["trigger"]["session_id"] == "ses_new"
    assert data["trigger"]["bound_by_client"] == "tm_home"
    assert persisted == []


def test_bullet_commit_projects_tunnel_node_then_persists_entry(monkeypatch):
    monkeypatch.setattr(
        "dual_tmux.binding.occupancy_context",
        lambda _name: ("tm_home", True, ""),
    )
    persisted = []
    monkeypatch.setattr(
        "dual_tmux.binding.persist_run_entry",
        lambda *args: persisted.append(args),
    )

    def body(data, *_args):
        data["bullet"]["session_id"] = "ses_bullet"
        data["bullet"]["directory"] = "/ws"
        data["runtime"] = {
            "server": "root@box",
            "container": "c1",
            "directory": "/ws",
            "ssh_port": 22,
        }
        data["run_point"] = {
            "kind": "docker",
            "ssh": "root@box",
            "container": "c1",
            "directory": "/ws",
        }
        return True

    data = _data()
    original_runtime = dict(data["runtime"])
    assert run_freeze_attempt(data, "bullet", "run_demo", "auto", False, body=body) is True
    assert data["bullet"]["session_id"] == "ses_bullet"
    assert data["runtime"]["server"] == "root@box"
    assert data["runtime"]["container"] == "c1"
    assert data["runtime"]["directory"] == "/ws"
    assert "c1" in data["runtime"]["cmd"]
    assert data["run_point"]["container"] == "c1"
    assert persisted == [("run_demo", data["runtime"]["cmd"])]
    node = from_legacy_tunnel(data)
    assert node.bullet is not None
    assert node.bullet.session.session_id == "ses_bullet"
    assert node.endpoint.kind == "docker"
    assert original_runtime != data["runtime"]


def test_persist_failure_keeps_original_binding(monkeypatch):
    monkeypatch.setattr(
        "dual_tmux.binding.occupancy_context",
        lambda _name: ("tm_home", True, ""),
    )

    def boom(*_args):
        raise OSError("entry write failed")

    monkeypatch.setattr("dual_tmux.binding.persist_run_entry", boom)

    def body(data, *_args):
        data["bullet"]["session_id"] = "ses_bullet"
        data["runtime"] = {
            "server": "root@box",
            "container": "c1",
            "directory": "/ws",
            "ssh_port": 22,
        }
        return True

    data = _data()
    assert run_freeze_attempt(data, "bullet", "run_demo", "auto", False, body=body) is False
    assert data["bullet"]["session_id"] == ""
    assert data["runtime"] == {"server": "box", "directory": "/old"}
