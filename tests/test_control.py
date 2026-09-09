import json

import pytest

from dual_tmux.config import AppConfig
from dual_tmux.control import ControlError, ControlService, operation_catalog
from dual_tmux.store import save, tunnels_dir


@pytest.fixture(autouse=True)
def _isolate_control_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "dual-tmux-home"))


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
        "session.resume.plan",
        "ownership.get",
        "ownership.handoff",
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


def test_send_checks_ownership_before_writing_tmux(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    save(tunnels_dir() / "dt-msg.json", _tunnel())
    monkeypatch.setattr(
        "dual_tmux.hub.require_active",
        lambda _data: (_ for _ in ()).throw(SystemExit("foreign owner")),
    )
    monkeypatch.setattr(
        "dual_tmux.control.tmux_ops.send_keys",
        lambda *_a, **_kw: pytest.fail("fenced Client must not receive input"),
    )

    with pytest.raises(ControlError, match="foreign owner"):
        ControlService().send("msg", "hello", "trigger")


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
    from dual_tmux import cli, ownership

    data = _tunnel()
    monkeypatch.setattr(
        cli,
        "_apply_freeze_legacy",
        lambda name, sides, tool: {**data, "call": [name, sides, tool]},
    )
    monkeypatch.setattr(
        cli,
        "_apply_resume_legacy",
        lambda name, force, **_kwargs: {**data, "call": [name, force]},
    )
    monkeypatch.setattr(
        ControlService, "get_tunnel", lambda self, name: type("R", (), {"data": data})()
    )
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda self, name: data)
    monkeypatch.setattr(
        cli,
        "_apply_model_legacy",
        lambda name, model, sides: {**data, "call": [name, model, sides]},
    )
    service = ControlService()
    monkeypatch.setattr(ownership, "plan_resume", lambda _data: {"safe": True})
    monkeypatch.setattr(
        ownership,
        "acquire_for_resume",
        lambda *_a, **_kw: {"generation": 1, "newly_acquired": False},
    )
    monkeypatch.setattr(
        ownership,
        "verify_resume",
        lambda *_a, **_kw: {
            "generation": 1,
            "writers": {
                "trigger": {"status": "ok", "count": 1, "pids": [10]},
                "bullet": {"status": "ok", "count": 1, "pids": [11]},
            },
        },
    )
    monkeypatch.setattr("dual_tmux.hub.renew_ownership", lambda *_a, **_kw: None)
    monkeypatch.setattr("dual_tmux.store.save", lambda *_a, **_kw: None)
    monkeypatch.setattr("dual_tmux.store.find_dt", lambda *_a, **_kw: None)
    monkeypatch.setattr("dual_tmux.hub.push_best_effort", lambda *_a, **_kw: None)
    assert service.freeze("msg", ["trigger"], "auto").data["call"] == [
        "msg",
        ["trigger"],
        "auto",
    ]
    assert service.resume("msg", True).data["call"] == ["msg", True]
    shadow_files = list(
        (tunnels_dir().parent / "fsm-shadow" / "resume").glob("*.json")
    )
    assert len(shadow_files) == 1
    assert json.loads(shadow_files[0].read_text())["state"] == "completed"
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
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda self, name: data)
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


def test_resume_commit_failure_releases_new_generation_without_save(monkeypatch):
    from dual_tmux import cli, hub, ownership

    data = _tunnel()
    service = ControlService()
    monkeypatch.setattr(
        ControlService, "get_tunnel", lambda self, name: type("R", (), {"data": data})()
    )
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda self, name: data)
    monkeypatch.setattr(ownership, "plan_resume", lambda _data: {"safe": True})
    monkeypatch.setattr(
        ownership,
        "acquire_for_resume",
        lambda *_a, **_kw: {"generation": 12, "newly_acquired": True},
    )
    monkeypatch.setattr(
        cli,
        "_apply_resume_legacy",
        lambda *_a, **_kw: (_ for _ in ()).throw(SystemExit("commit failed")),
    )
    released = []
    monkeypatch.setattr(hub, "park_local", lambda _data: [])
    monkeypatch.setattr(
        hub, "release", lambda name, **kw: released.append((name, kw["generation"]))
    )
    monkeypatch.setattr(
        "dual_tmux.store.save", lambda *_a: pytest.fail("must not save partial binding")
    )
    with pytest.raises(ControlError, match="commit failed"):
        service.resume("dt-msg")
    assert released == [("dt-msg", 12)]


def test_resume_rejects_missing_remote_session_before_ownership(monkeypatch):
    from dual_tmux import oc, ownership, recovery

    data = _tunnel()
    data["runtime"] = {"server": "box", "container": ""}
    data["bullet"]["session_id"] = "ses_missing"
    service = ControlService()
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda self, name: data)
    monkeypatch.setattr(
        recovery,
        "reconcile_remote_runtime",
        lambda _data: {"status": "missing", "changed": False, "locations": []},
    )
    monkeypatch.setattr(oc, "persist_snapshot", lambda _side: None)
    monkeypatch.setattr(
        ownership,
        "plan_resume",
        lambda _data: pytest.fail("must reject before ownership planning"),
    )

    with pytest.raises(ControlError) as caught:
        service.resume("dt-msg")
    assert caught.value.code == "session_missing"


def test_resume_persists_unique_runtime_repair_before_ownership(monkeypatch):
    from dual_tmux import cli, hub, ownership, recovery

    data = _tunnel()
    data.update(run="run_msg", runtime={"server": "box", "container": ""})
    data["bullet"]["session_id"] = "ses_remote"
    service = ControlService()
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda self, name: data)

    def repair(value):
        value["runtime"].update(container="work", cmd="ssh box docker exec work")
        return {
            "status": "repaired",
            "changed": True,
            "locations": [{"location": "work", "container": "work"}],
        }

    monkeypatch.setattr(recovery, "reconcile_remote_runtime", repair)
    saved = []
    entries = []
    monkeypatch.setattr("dual_tmux.store.find_dt", lambda _name: "binding")
    monkeypatch.setattr(
        "dual_tmux.store.save", lambda path, value: saved.append((path, value.copy()))
    )
    monkeypatch.setattr(cli, "write_entry", lambda run, cmd: entries.append((run, cmd)))
    monkeypatch.setattr(hub, "sync_best_effort", lambda: None)
    monkeypatch.setattr(cli, "_preflight_resume_snapshots", lambda _data: None)
    monkeypatch.setattr(
        ownership,
        "plan_resume",
        lambda _data: (_ for _ in ()).throw(SystemExit("stop")),
    )

    with pytest.raises(ControlError, match="stop"):
        service.resume("dt-msg")
    assert saved and saved[0][0] == "binding"
    assert entries == [("run_msg", "ssh box docker exec work")]


def test_native_pull_failure_releases_new_generation_before_commit(monkeypatch):
    from dual_tmux import cli, hotfix, hub, ownership

    data = _tunnel()
    data["trigger"] = {
        "tool": "codex",
        "session_id": "00000000-0000-0000-0000-000000000001",
    }
    service = ControlService()
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda self, name: data)
    monkeypatch.setattr(ownership, "plan_resume", lambda _data: {"safe": True})
    monkeypatch.setattr(
        ownership,
        "acquire_for_resume",
        lambda *_a, **_kw: {"generation": 13, "newly_acquired": True},
    )
    monkeypatch.setattr(
        "dual_tmux.config.load_config",
        lambda: AppConfig(client="tm_a", server="tom7r", user="andy"),
    )
    monkeypatch.setattr(
        hotfix,
        "sync_persist",
        lambda *_a: (_ for _ in ()).throw(SystemExit("native pull failed")),
    )
    monkeypatch.setattr(
        cli,
        "_apply_resume_legacy",
        lambda *_a, **_kw: pytest.fail("commit must not start"),
    )
    released = []
    monkeypatch.setattr(
        hub, "release", lambda name, **kw: released.append((name, kw["generation"]))
    )

    with pytest.raises(ControlError, match="native pull failed"):
        service.resume("dt-msg")
    assert released == [("dt-msg", 13)]


def test_resume_snapshot_preflight_rejects_before_claim_or_tmux(monkeypatch):
    from dual_tmux import cli, ownership

    data = _tunnel()
    service = ControlService()
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda *_a: data)
    monkeypatch.setattr(
        cli,
        "_preflight_resume_snapshots",
        lambda _data: (_ for _ in ()).throw(SystemExit("snapshot_conflict")),
    )
    monkeypatch.setattr(
        ownership,
        "acquire_for_resume",
        lambda *_a, **_kw: pytest.fail("must not claim before snapshot preflight"),
    )
    monkeypatch.setattr(
        cli,
        "_apply_resume_legacy",
        lambda *_a, **_kw: pytest.fail("must not mutate tmux before preflight"),
    )

    with pytest.raises(ControlError, match="snapshot_conflict"):
        service.resume("dt-msg")


def test_resume_keeps_short_lease_alive_during_restore(monkeypatch):
    import time

    from dual_tmux import cli, hub, ownership

    data = _tunnel()
    service = ControlService()
    renewals = []
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda *_a: data)
    monkeypatch.setattr(cli, "_preflight_resume_snapshots", lambda _data: None)
    monkeypatch.setattr(ownership, "plan_resume", lambda _data: {"safe": True})
    monkeypatch.setattr(
        ownership,
        "acquire_for_resume",
        lambda *_a, **_kw: {"generation": 21, "newly_acquired": False},
    )
    monkeypatch.setattr(ownership, "verify_resume", lambda *_a: {"generation": 21})
    monkeypatch.setattr(hub, "enabled", lambda: True)
    monkeypatch.setattr(
        hub,
        "renew_ownership",
        lambda name, generation: renewals.append((name, generation)),
    )
    monkeypatch.setattr(
        cli,
        "_apply_resume_legacy",
        lambda *_a, **_kw: time.sleep(1.1) or data.copy(),
    )
    monkeypatch.setattr("dual_tmux.store.save", lambda *_a: None)
    monkeypatch.setattr("dual_tmux.store.find_dt", lambda *_a: None)
    monkeypatch.setattr(hub, "push_best_effort", lambda: None)

    assert service.resume("dt-msg").data["ownership_generation"] == 21
    assert len(renewals) >= 2
    assert set(renewals) == {("dt-msg", 21)}


def test_cached_web_preflight_never_runs_live_snapshot(tmp_path, monkeypatch):
    from dual_tmux import ownership

    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    data = _tunnel()
    data["trigger"]["session_id"] = "trigger-1"
    data["bullet"]["session_id"] = "bullet-1"
    save(tunnels_dir() / "dt-msg.json", data)
    facts = {
        "schema": 1,
        "name": "dt-msg",
        "takeover": {"safe": True, "action": "resume", "reason": "already_owned"},
    }
    ownership.write_cache(facts)
    monkeypatch.setattr(
        ownership, "snapshot", lambda *_a, **_kw: pytest.fail("must not probe")
    )
    service = ControlService()
    assert service.cached_ownership("dt-msg").data["facts"] == facts
    plan = service.cached_resume_plan("dt-msg").data
    assert plan["safe"] is True
    assert plan["action"] == "resume"


def test_handoff_rechecks_live_plan_before_remote_request(monkeypatch):
    from dual_tmux import hub, ownership

    service = ControlService()
    data = _tunnel()
    monkeypatch.setattr(ControlService, "_get_tunnel_readonly", lambda *_a: data)
    monkeypatch.setattr(
        ownership,
        "plan_resume",
        lambda _data: {
            "safe": False,
            "action": "stop",
            "reason": "bullet_duplicate_writer",
        },
    )
    monkeypatch.setattr(
        hub, "request_handoff", lambda *_a, **_kw: pytest.fail("must not request")
    )
    with pytest.raises(ControlError) as caught:
        service.handoff("dt-msg")
    assert caught.value.code == "handoff_preflight_rejected"
    assert caught.value.detail["reason"] == "bullet_duplicate_writer"


def test_cached_foreign_evidence_expires_independently_of_cache(tmp_path, monkeypatch):
    from dual_tmux import ownership

    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    data = _tunnel()
    data["trigger"]["session_id"] = "trigger-1"
    data["bullet"]["session_id"] = "bullet-1"
    save(tunnels_dir() / "dt-msg.json", data)
    facts = {
        "schema": 1,
        "name": "dt-msg",
        "lease": {"state": "foreign", "evidence": {"sampled_at": 100}},
        "takeover": {
            "safe": True,
            "action": "request_handoff",
            "reason": "foreign_idle_detached",
        },
    }
    ownership.write_cache(facts, now=250)
    monkeypatch.setattr(ownership.time, "time", lambda: 260)
    monkeypatch.setattr("dual_tmux.control.time.time", lambda: 400)
    plan = ControlService().cached_resume_plan("dt-msg").data
    assert plan["safe"] is True
    assert plan["action"] == "request_handoff"
    assert plan["reason"] == "owner_evidence_stale"
