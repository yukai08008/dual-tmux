import pytest

from dual_tmux import cli
from dual_tmux import recovery
from dual_tmux import workpoint as wp


def _dst(server: str = "box") -> dict:
    return {
        "name": "dt-msg",
        "op": "op_msg",
        "run": "run_msg",
        "runtime": {
            "server": server,
            "container": "",
            "directory": "/workspace",
            "cmd": "ssh -t box",
        },
        "trigger": {"tool": "opencode", "session_id": "ses_trigger"},
        "bullet": {"tool": "opencode", "session_id": "ses_bullet"},
    }


def test_capture_runtime_clears_stale_remote_target_for_local_bullet():
    data = _dst()
    wp.capture_runtime(
        data,
        {
            "kind": "local",
            "cwd": "/Users/andy/project",
            "directory": "/Users/andy/project",
        },
    )
    assert data["runtime"] == {
        "server": "",
        "container": "",
        "directory": "/Users/andy/project",
        "cmd": "",
    }


def test_prompt_status_does_not_fabricate_a_host_hop():
    pane = """
 andy_ouc@Mac  ~/.dual-tmux  opencode --auto -s ses_old
 ✘ andy_ouc@Mac  ~/.dual-tmux 
"""
    assert wp.parse_hops(pane) == []


def test_discover_prefers_live_local_agent_over_historical_ssh(monkeypatch):
    monkeypatch.setattr(
        wp.tmux_ops,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": "opencode", "cwd": "/local/project"},
    )
    monkeypatch.setattr(
        wp.tmux_ops,
        "capture_pane",
        lambda _name: "local@mac  ~  ssh box\nroot@box:/workspace# opencode",
    )
    monkeypatch.setattr(wp, "walk_commands", lambda _pid: ["opencode"])
    point = wp.discover("run_msg")
    assert point["kind"] == "local"
    assert point["cwd"] == "/local/project"
    assert point["ssh"] == ""


def _patch_resume(monkeypatch, data: dict):
    monkeypatch.setattr(cli, "_resolve", lambda _name: data)
    monkeypatch.setattr(cli.hub, "require_active", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli.hub, "push_best_effort", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli.opsdir, "prepare", lambda _data: None)
    monkeypatch.setattr(cli.oc_ops, "is_dst", lambda _data: True)
    monkeypatch.setattr(cli.wp, "stamp", lambda *_args: None)
    monkeypatch.setattr(cli.wp, "discover", lambda _name: {})
    monkeypatch.setattr(cli, "save", lambda *_args: None)
    monkeypatch.setattr(cli, "find_dt", lambda _name: None)
    monkeypatch.setattr(cli.ev, "emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(recovery, "ensure_remote_session", lambda *_args, **_kwargs: False)


def test_resume_stops_before_session_command_when_jump_does_not_stay(monkeypatch):
    data = _dst()
    _patch_resume(monkeypatch, data)
    calls = []
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "zsh")
    monkeypatch.setattr(cli.tmux_ops, "reconnect", lambda name, cmd: calls.append(("jump", name, cmd)))
    monkeypatch.setattr(cli.tmux_ops, "wait_stable_command", lambda *_args, **_kwargs: "zsh")
    monkeypatch.setattr(cli, "_start_side", lambda *_args, **_kwargs: calls.append(("start",)))

    with pytest.raises(SystemExit, match="stopped before sending"):
        cli._apply_resume_legacy("msg")
    assert calls == [("jump", "run_msg", "ssh -t box")]


def test_resume_waits_for_remote_jump_before_starting_bullet(monkeypatch):
    data = _dst()
    _patch_resume(monkeypatch, data)
    calls = []
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "zsh")
    monkeypatch.setattr(cli.tmux_ops, "reconnect", lambda *_args: calls.append("jump"))
    monkeypatch.setattr(
        cli.tmux_ops,
        "wait_stable_command",
        lambda *_args, **_kwargs: calls.append("landed") or "ssh",
    )
    monkeypatch.setattr(cli.oc_ops, "ensure_local", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(cli, "_start_side", lambda _data, _tmux, side, *_args: calls.append(side))

    cli._apply_resume_legacy("msg")
    assert calls == ["jump", "landed", "trigger", "bullet"]


def test_resume_imports_local_bullet_snapshot(monkeypatch):
    data = _dst(server="")
    data["runtime"]["cmd"] = ""
    _patch_resume(monkeypatch, data)
    seen = []
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "zsh")
    monkeypatch.setattr(
        cli.oc_ops,
        "ensure_local",
        lambda info, **kwargs: seen.append((info["session_id"], kwargs.get("role", "trigger"))) or False,
    )
    monkeypatch.setattr(cli, "_start_side", lambda *_args, **_kwargs: None)

    cli._apply_resume_legacy("msg")
    assert seen == [("ses_trigger", "trigger"), ("ses_bullet", "bullet")]
