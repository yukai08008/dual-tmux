import json
import time
from pathlib import Path

import pytest

from dual_tmux import cli, log, recovery
from dual_tmux.control import ControlService
from dual_tmux.store import save, tunnels_dir

SKILLS = Path(__file__).resolve().parent.parent / "src" / "dual_tmux" / "skills"


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))


def _tunnel(remote: bool = True) -> dict:
    runtime = (
        {"server": "box", "container": "c1", "directory": "/workspace", "cmd": "ssh box"}
        if remote
        else {"directory": "/tmp", "cmd": ""}
    )
    return {
        "name": "dt-x",
        "op": "op_x",
        "run": "run_x",
        "trigger": {"tool": "opencode"},
        "bullet": {"tool": "opencode", "session_id": "ses_b1"},
        "runtime": runtime,
    }


def _write_evidence(name: str, bullet_state: str, trigger_state: str = "idle") -> None:
    from dual_tmux.activity import evidence_path

    now = int(time.time())
    doc = {
        "schema": 1,
        "name": name,
        "sampled_at": now,
        "sides": {
            role: {
                "state": bullet_state if role == "bullet" else trigger_state,
                "last_semantic_change_at": now - 500,
                "sampled_at": now,
                "runtime": "agent",
                "probe_status": "ok",
            }
            for role in ("trigger", "bullet")
        },
    }
    path = evidence_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _write_health(name: str, status: str = "idle", failures: int = 0) -> None:
    path = recovery.state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"status": status, "consecutive_failures": failures}),
        encoding="utf-8",
    )


def _snapshot_env(monkeypatch, bullet_state: str, pane_cmd: str, pids, remote=True):
    data = _tunnel(remote)
    save(tunnels_dir() / "dt-x.json", data)
    _write_evidence("dt-x", bullet_state)
    _write_health("dt-x")
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _pane: pane_cmd)
    monkeypatch.setattr(
        "dual_tmux.recovery.remote_session_pids", lambda _data: pids
    )
    return data


# --- dt bullet ----------------------------------------------------------


def test_bullet_snapshot_ok_to_dispatch(monkeypatch):
    _snapshot_env(monkeypatch, "idle", "ssh", [101])
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["hint"] == "ok_to_dispatch"
    assert snap["sides"]["bullet"]["state"] == "idle"
    assert snap["sides"]["bullet"]["no_progress_seconds"] >= 500
    assert snap["writers"] == {"status": "single", "count": 1, "pids": [101]}
    assert snap["transport"] == {"pane_cmd": "ssh", "remote": True}


def test_bullet_snapshot_stalled_hint(monkeypatch):
    _snapshot_env(monkeypatch, "stalled", "ssh", [101])
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["hint"].startswith("stalled_no_progress_")
    assert "do_not_queue" in snap["hint"]


def test_bullet_snapshot_multiple_writers_hint(monkeypatch):
    _snapshot_env(monkeypatch, "idle", "ssh", [101, 202])
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["hint"] == "multiple_writers_fence_first_dt_rebuild"


def test_bullet_snapshot_transport_down_hint(monkeypatch):
    _snapshot_env(monkeypatch, "idle", "zsh", [101])
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["hint"] == "transport_down_dt_rebuild"


def test_bullet_snapshot_working_hint(monkeypatch):
    _snapshot_env(monkeypatch, "working", "ssh", [101])
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["hint"] == "working_wait_for_turn_end"


def test_bullet_snapshot_probe_failing_hint(monkeypatch):
    _snapshot_env(monkeypatch, "idle", "ssh", [101])
    _write_health("dt-x", status="degraded", failures=3)
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["hint"] == "probe_failing_check_dt_health"


def test_bullet_snapshot_defaults_and_readonly(monkeypatch):
    data = _tunnel(remote=False)
    save(tunnels_dir() / "dt-x.json", data)
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _pane: "opencode")
    called = []
    monkeypatch.setattr(
        "dual_tmux.recovery.remote_session_pids",
        lambda _data: called.append(1),
    )
    log.emit("bullet.send", name="dt-x", chars=3, preview="hi")
    before = len(log.read_events(limit=500))
    snap = cli._bullet_snapshot(cli._resolve("dt-x"))
    assert snap["hint"] == "ok_to_dispatch"
    assert snap["writers"]["status"] == "not_remote"
    assert not called  # local tunnel must not probe remote pids
    assert snap["events"] and snap["events"][-1]["kind"] == "bullet.send"
    assert len(log.read_events(limit=500)) == before  # read path emits nothing


def test_cmd_bullet_json_output(monkeypatch, capsys):
    _snapshot_env(monkeypatch, "idle", "ssh", [101])
    cli.cmd_bullet(type("Args", (), {"name": "dt-x", "json": True})())
    payload = json.loads(capsys.readouterr().out)
    assert payload["hint"] == "ok_to_dispatch"
    assert payload["schema"] == 1


# --- dt rebuild ---------------------------------------------------------


def _rebuild_env(monkeypatch, bullet_state: str, *, force: bool = False):
    data = _tunnel()
    save(tunnels_dir() / "dt-x.json", data)
    _write_evidence("dt-x", bullet_state)
    order = []
    monkeypatch.setattr(cli.hub, "require_active", lambda _d: {})
    monkeypatch.setattr(cli.hub, "push_best_effort", lambda *a, **k: None)
    monkeypatch.setattr(
        "dual_tmux.recovery.reconcile_remote_runtime",
        lambda _d, **_kw: order.append("reconcile") or {"status": "healthy", "changed": False, "locations": []},
    )
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _pane: order.append("pane") or "ssh")
    monkeypatch.setattr(
        "dual_tmux.recovery.fence_remote_bullet",
        lambda _d, **_kw: order.append("fence") or [],
    )
    monkeypatch.setattr(cli, "_pane_shows_agent", lambda _pane: order.append("shows") or False)
    monkeypatch.setattr(
        "dual_tmux.recovery.ensure_remote_session",
        lambda _d, **_kw: order.append("persist") or False,
    )
    monkeypatch.setattr(
        cli, "_start_side", lambda data, pane, side, model="", resume=False: order.append("start")
    )
    return data, order


def test_rebuild_refuses_working_bullet_without_force(monkeypatch):
    _rebuild_env(monkeypatch, "working")
    with pytest.raises(SystemExit, match="working"):
        cli._apply_rebuild_legacy("dt-x", force=False)
    rows = log.read_events(limit=10, kind="bullet.rebuild")
    kinds = [r["kind"] for r in rows]
    assert "bullet.rebuild.start" in kinds
    assert kinds[-1] == "bullet.rebuild.fail"


def test_rebuild_force_overrides_working_and_runs_pipeline(monkeypatch):
    _rebuild_env(monkeypatch, "working", force=True)
    data = cli._apply_rebuild_legacy("dt-x", force=True)
    assert data["name"] == "dt-x"
    rows = log.read_events(limit=10, kind="bullet.rebuild")
    assert rows[-1]["kind"] == "bullet.rebuild.ok"


def test_rebuild_remote_pipeline_order(monkeypatch):
    _, order = _rebuild_env(monkeypatch, "stalled")
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_command",
        lambda _pane: "zsh",  # forces the reconnect branch
    )
    monkeypatch.setattr(cli.tmux_ops, "reconnect", lambda pane, cmd: order.append("reconnect"))
    monkeypatch.setattr(
        cli.tmux_ops,
        "wait_stable_command",
        lambda _pane, _want, timeout=25: order.append("wait") or "ssh",
    )
    cli._apply_rebuild_legacy("dt-x")
    assert order == ["reconcile", "reconnect", "wait", "fence", "shows", "persist", "start"]


def test_rebuild_refuses_blind_when_probe_fails(monkeypatch):
    _rebuild_env(monkeypatch, "stalled")
    monkeypatch.setattr(
        "dual_tmux.recovery.fence_remote_bullet", lambda _d, **_kw: None
    )
    with pytest.raises(SystemExit, match="refusing to rebuild blind"):
        cli._apply_rebuild_legacy("dt-x")
    rows = log.read_events(limit=10, kind="bullet.rebuild")
    assert rows[-1]["kind"] == "bullet.rebuild.fail"


def test_control_rebuild_wraps_legacy_and_validates_node(monkeypatch):
    data = _tunnel()
    save(tunnels_dir() / "dt-x.json", data)
    monkeypatch.setattr(cli, "_apply_rebuild_legacy", lambda name, force=False: dict(data))
    result = ControlService().rebuild("dt-x", force=False)
    assert result.operation == "bullet.rebuild"
    assert result.ok
    assert result.data["name"] == "dt-x"


def test_control_rebuild_requires_bullet_pane(tmp_path, monkeypatch):
    from dual_tmux.control import ControlError

    service = ControlService()
    monkeypatch.setattr(
        service,
        "get_tunnel",
        lambda _name: type("T", (), {"data": {"name": "dt-x"}})(),
    )
    with pytest.raises(ControlError, match="bullet pane"):
        service.rebuild("dt-x")


# --- skills and registry ------------------------------------------------


def test_tmux_trigger_skill_teaches_controlled_verbs():
    text = (SKILLS / "tmux-trigger" / "SKILL.md").read_text(encoding="utf-8")
    assert "dt send" in text
    assert "dt bullet" in text
    assert "dt rebuild" in text
    assert "dt log --name" in text


def test_dual_tmux_skill_and_agents_text_teach_controlled_verbs(tmp_path, monkeypatch):
    text = (SKILLS / "dual-tmux" / "SKILL.md").read_text(encoding="utf-8")
    assert "dt send" in text and "dt rebuild" in text and "dt bullet" in text
    from dual_tmux import opsdir

    agents = opsdir.agents_text(_tunnel())
    assert "dt send dt-x" in agents
    assert "dt bullet" in agents
    assert "dt rebuild" in agents
    assert "dt log --name dt-x --cat bullet" in agents


def test_kind_meta_covers_rebuild_span():
    for kind in ("bullet.rebuild.start", "bullet.rebuild.ok", "bullet.rebuild.fail"):
        assert kind in log.KIND_META
        assert log.meta(kind)["cat"] == "bullet"
    assert log.meta("bullet.rebuild.fail")["sev"] == "error"
    assert log.meta("bullet.rebuild.ok")["label"] == "Bullet 围栏重建完成"
