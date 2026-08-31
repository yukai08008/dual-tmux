import pytest

from dual_tmux.control import ControlError, ControlService, operation_catalog
from dual_tmux.store import save, tunnels_dir


def _tunnel(tool: str = "opencode") -> dict:
    return {
        "name": "dt-msg",
        "op": "op_msg",
        "run": "run_msg",
        "trigger": {"tool": tool},
        "bullet": {"tool": tool},
    }


def test_operation_catalog_has_control_metadata():
    rows = operation_catalog()
    assert {row["name"] for row in rows} == {
        "tunnel.list",
        "tunnel.get",
        "pane.send",
        "session.freeze",
        "session.resume",
        "agent.model",
        "tunnel.create",
        "tunnel.remove",
        "tunnel.reconnect",
        "tunnel.drop",
        "hub.push",
        "hub.pull",
        "config.switch",
        "health.probe",
        "health.recover",
        "health.auto",
        "memory.get",
        "memory.fact",
        "memory.note",
        "events.list",
        "doctor.run",
    }
    assert all(
        row["capability"] and row["risk"] and row["surfaces"] and row["audit_event"]
        for row in rows
    )
    assert all("feishu" in row["surfaces"] for row in rows)


def test_list_get_and_send_return_structured_results(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    save(tunnels_dir() / "dt-msg.json", _tunnel("codex"))
    sent = []
    monkeypatch.setattr(
        "dual_tmux.control.tmux_ops.send_keys",
        lambda pane, text: sent.append((pane, text)),
    )
    service = ControlService()

    listed = service.list_tunnels()
    assert listed.operation == "tunnel.list"
    assert listed.data[0]["name"] == "dt-msg"
    assert service.get_tunnel("msg").data["run"] == "run_msg"
    result = service.send("msg", "hello", "bullet")
    assert result.as_dict()["ok"] is True
    assert result.data == {"pane": "run_msg", "side": "bullet"}
    assert sent == [("run_msg", "hello")]


def test_get_without_name_uses_latest_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    save(tunnels_dir() / "dt-msg.json", _tunnel())
    assert ControlService().get_tunnel(None).data["name"] == "dt-msg"


def test_control_errors_are_structured(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    service = ControlService()
    with pytest.raises(ControlError) as caught:
        service.get_tunnel("missing")
    assert caught.value.status == 404
    assert caught.value.as_dict()["error"]["code"] == "operation_failed"

    save(tunnels_dir() / "dt-msg.json", _tunnel())
    with pytest.raises(ControlError, match="unsupported side") as caught:
        service.send("msg", "hello", "wrong")
    assert caught.value.code == "invalid_side"


def test_model_rejects_agent_without_capability(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    save(tunnels_dir() / "dt-msg.json", _tunnel("claude"))
    with pytest.raises(ControlError) as caught:
        ControlService().model("msg", "provider/model", ["trigger"])
    assert caught.value.code == "capability_not_supported"
    assert caught.value.detail == {"agent": "claude", "capability": "model"}


def test_control_wraps_legacy_freeze_resume_and_model(monkeypatch):
    from dual_tmux import cli

    data = _tunnel()
    monkeypatch.setattr(
        cli,
        "_apply_freeze_legacy",
        lambda name, sides, tool: {**data, "call": [name, sides, tool]},
    )
    monkeypatch.setattr(
        cli, "_apply_resume_legacy", lambda name, force: {**data, "call": [name, force]}
    )
    monkeypatch.setattr(
        ControlService, "get_tunnel", lambda self, name: type("R", (), {"data": data})()
    )
    monkeypatch.setattr(
        cli,
        "_apply_model_legacy",
        lambda name, model, sides: {**data, "call": [name, model, sides]},
    )
    service = ControlService()
    assert service.freeze("msg", ["trigger"], "auto").data["call"] == [
        "msg",
        ["trigger"],
        "auto",
    ]
    assert service.resume("msg", True).data["call"] == ["msg", True]
    assert service.model("msg", "p/m", ["trigger"]).data["call"] == [
        "msg",
        "p/m",
        ["trigger"],
    ]


def test_remove_and_force_recovery_require_confirmation(monkeypatch):
    service = ControlService()
    data = _tunnel()
    monkeypatch.setattr(
        ControlService, "get_tunnel", lambda self, name: type("R", (), {"data": data})()
    )
    with pytest.raises(ControlError) as caught:
        service.remove_tunnel("msg", confirm="wrong")
    assert caught.value.code == "confirmation_required"
    with pytest.raises(ControlError) as caught:
        service.recover("msg", force=True, confirm="wrong")
    assert caught.value.code == "confirmation_required"


def test_control_hub_health_and_auto_delegate(monkeypatch):
    from dual_tmux import hub, recovery

    service = ControlService()
    data = _tunnel()
    monkeypatch.setattr(
        ControlService, "get_tunnel", lambda self, name: type("R", (), {"data": data})()
    )
    monkeypatch.setattr(hub, "push", lambda: "remote-root")
    monkeypatch.setattr(hub, "pull", lambda: "local-root")
    monkeypatch.setattr(recovery, "observe", lambda data, auto=False: {"healthy": True})
    monkeypatch.setattr(
        recovery,
        "set_enabled",
        lambda name, enabled: {"name": name, "auto_recover": enabled},
    )

    assert service.hub_sync("push").data["destination"] == "remote-root"
    assert service.hub_sync("pull").data["destination"] == "local-root"
    assert service.probe_health("msg").data["healthy"] is True
    assert service.set_auto_recover("msg", True).data["auto_recover"] is True


def test_switch_mode_requires_explicit_confirmation():
    with pytest.raises(ControlError) as caught:
        ControlService().switch_mode(
            mode="local", client="tm_test", workspace="/tmp", confirm=""
        )
    assert caught.value.code == "confirmation_required"
