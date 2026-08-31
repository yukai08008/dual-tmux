import json
import subprocess

from dual_tmux import recovery
from dual_tmux.cli import build_parser
from dual_tmux.config import AppConfig, write_config
from dual_tmux.store import load, save, tunnels_dir


def tunnel(enabled=False, remote=False):
    return {
        "name": "dt-msg",
        "op": "op_msg",
        "run": "run_msg",
        "auto_recover": enabled,
        "runtime": {
            "server": "box" if remote else "",
            "container": "agent-box" if remote else "",
            "directory": "/workspace/app",
            "cmd": "ssh box",
        },
        "trigger": {"tool": "opencode", "session_id": "ses_trigger1"},
        "bullet": {"tool": "opencode", "session_id": "ses_bullet1"},
    }


def result(ok):
    return {
        "healthy": ok,
        "checked_at": "2026-08-31T10:00:00+08:00",
        "failures": [] if ok else ["transport"],
        "layers": {"transport": {"ok": ok, "status": "connected" if ok else "unreachable"}},
    }


def test_three_failures_are_required_and_disabled_never_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    calls = []
    data = tunnel(enabled=False)
    for now in (1, 2, 3):
        state = recovery.observe(data, now=now, prober=lambda _: result(False), recoverer=lambda _: calls.append(1))
    assert calls == []
    assert state["status"] == "degraded"
    assert state["consecutive_failures"] == 3


def test_enabled_recovers_on_third_failure_and_health_resets(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    calls = []
    data = tunnel(enabled=True)
    for now in (1, 2, 3):
        state = recovery.observe(
            data,
            now=now,
            prober=lambda _: result(False),
            recoverer=lambda _: calls.append(1) or result(True),
        )
    assert len(calls) == 1
    assert state["status"] == "healthy"
    assert state["consecutive_failures"] == 0


def test_backoff_and_fifth_failure_open_circuit(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    data = tunnel(enabled=True)
    now = 100
    for attempt in range(5):
        state = recovery.read_state(data["name"])
        state["consecutive_failures"] = 2
        state["next_retry_at"] = 0
        recovery.save_state(state)
        state = recovery.observe(
            data,
            now=now,
            prober=lambda _: result(False),
            recoverer=lambda _: (_ for _ in ()).throw(SystemExit("offline")),
        )
        assert state["next_retry_at"] == now + recovery.BACKOFF_SECONDS[attempt]
        now = state["next_retry_at"]
    assert state["status"] == "attention"
    assert state["circuit_until"] > 0


def test_remote_probe_fails_closed_when_recorded_container_is_stopped(monkeypatch):
    monkeypatch.setattr("dual_tmux.cli.require_config", lambda: AppConfig(client="tm_x", server="box", user="u"))

    def runner(argv, **kwargs):
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(argv, 1, "false\n", "No such container")

    layers = recovery._remote_probe(tunnel(remote=True), runner=runner)
    assert layers["transport"]["ok"] is True
    assert layers["container"]["ok"] is False
    assert layers["directory"]["status"] == "unknown"


def test_container_probe_ssh_failure_is_transport_failure(monkeypatch):
    monkeypatch.setattr("dual_tmux.cli.require_config", lambda: AppConfig(client="tm_x", server="box", user="u"))

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 255, "", "connection reset")

    layers = recovery._remote_probe(tunnel(remote=True), runner=runner)
    assert layers["transport"]["status"] == "unreachable"
    assert layers["container"]["status"] == "unknown"


def test_enable_is_persisted_without_touching_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_x"))
    data = tunnel()
    save(tunnels_dir() / "dt-msg.json", data)
    monkeypatch.setattr("dual_tmux.hub.push_best_effort", lambda **kwargs: None)
    recovery.set_enabled("dt-msg", True)
    saved = load(tunnels_dir() / "dt-msg.json")
    assert saved["auto_recover"] is True
    assert saved["bullet"]["session_id"] == "ses_bullet1"


def test_health_cache_is_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    state = recovery.read_state("dt-msg")
    state["status"] = "suspect"
    recovery.save_state(state)
    assert json.loads(recovery.state_path("dt-msg").read_text())["status"] == "suspect"


def test_health_and_recover_cli_contract():
    health = build_parser().parse_args(["health", "dt-msg", "--json"])
    assert health.command == "health" and health.json is True
    recover = build_parser().parse_args(["recover", "dt-msg", "--enable"])
    assert recover.command == "recover" and recover.enable is True
