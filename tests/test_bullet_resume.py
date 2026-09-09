import subprocess

import pytest

from dual_tmux import cli, recovery
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


def _location_runner(locations):
    output = "".join(
        f"DT_SESSION_LOCATION={location}\t{directory}\n"
        for location, directory in locations
    )

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, output, "")

    return run


def test_reconcile_remote_runtime_repairs_unique_container_location():
    data = _dst()
    result = recovery.reconcile_remote_runtime(
        data, runner=_location_runner([("work_box", "/workspace")])
    )
    assert result["status"] == "repaired"
    assert data["runtime"]["container"] == "work_box"
    assert "docker exec -it work_box" in data["runtime"]["cmd"]
    assert data["run_point"]["kind"] == "docker"
    assert data["run_point"]["container"] == "work_box"


def test_reconcile_remote_runtime_rejects_ambiguous_locations():
    data = _dst()
    result = recovery.reconcile_remote_runtime(
        data,
        runner=_location_runner([("work_a", "/workspace"), ("work_b", "/workspace")]),
    )
    assert result["status"] == "ambiguous"
    assert result["changed"] is False
    assert data["runtime"]["container"] == ""


def test_reconcile_remote_runtime_keeps_exact_configured_location():
    data = _dst()
    data["runtime"]["container"] = "work_box"
    result = recovery.reconcile_remote_runtime(
        data, runner=_location_runner([("work_box", "/workspace")])
    )
    assert result["status"] == "healthy"
    assert result["changed"] is False


def test_start_remote_bullet_is_idempotent_with_one_exact_writer(monkeypatch):
    data = _dst()
    monkeypatch.setattr(cli, "_pane_shows_agent", lambda _name: False)
    monkeypatch.setattr(recovery, "remote_session_pids", lambda _data: [42])
    monkeypatch.setattr(
        recovery,
        "fence_remote_bullet",
        lambda _data: pytest.fail("one exact writer must not be fenced"),
    )
    monkeypatch.setattr(
        cli.tmux_ops,
        "ensure_agent",
        lambda *_args, **_kwargs: pytest.fail("one exact writer must not restart"),
    )

    cli._start_side(data, "run_msg", "bullet", resume=True)


def test_start_remote_bullet_fences_duplicate_exact_writers(monkeypatch):
    data = _dst()
    monkeypatch.setattr(cli, "_pane_shows_agent", lambda _name: False)
    monkeypatch.setattr(recovery, "remote_session_pids", lambda _data: [42, 43])
    monkeypatch.setattr(recovery, "fence_remote_bullet", lambda _data: [42, 43])
    started = []
    monkeypatch.setattr(
        cli.tmux_ops,
        "ensure_agent",
        lambda *_args, **_kwargs: started.append(True) or True,
    )

    cli._start_side(data, "run_msg", "bullet", resume=True)
    assert started == [True]


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
    monkeypatch.setattr(cli, "_pane_shows_agent", lambda _name: False)
    monkeypatch.setattr(
        recovery, "ensure_remote_session", lambda *_args, **_kwargs: False
    )


def test_resume_stops_before_session_command_when_jump_does_not_stay(monkeypatch):
    data = _dst()
    _patch_resume(monkeypatch, data)
    calls = []
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "zsh")
    monkeypatch.setattr(
        cli.tmux_ops, "reconnect", lambda name, cmd: calls.append(("jump", name, cmd))
    )
    monkeypatch.setattr(
        cli.tmux_ops, "wait_stable_command", lambda *_args, **_kwargs: "zsh"
    )
    monkeypatch.setattr(
        cli, "_start_side", lambda *_args, **_kwargs: calls.append(("start",))
    )

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
    monkeypatch.setattr(
        cli, "_start_side", lambda _data, _tmux, side, *_args: calls.append(side)
    )

    cli._apply_resume_legacy("msg")
    assert calls == ["jump", "landed", "trigger", "bullet"]


def test_resume_does_not_recover_over_live_remote_bullet_tui(monkeypatch):
    data = _dst()
    _patch_resume(monkeypatch, data)
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "ssh")
    monkeypatch.setattr(cli, "_pane_shows_agent", lambda _name: True)
    monkeypatch.setattr(
        recovery,
        "ensure_remote_session",
        lambda _data: pytest.fail("must not import over a live remote bullet"),
    )
    monkeypatch.setattr(cli.oc_ops, "ensure_local", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(cli, "_start_side", lambda *_args, **_kwargs: None)

    cli._apply_resume_legacy("msg")


def test_resume_imports_local_bullet_snapshot(monkeypatch):
    data = _dst(server="")
    data["runtime"]["cmd"] = ""
    _patch_resume(monkeypatch, data)
    seen = []
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "zsh")
    monkeypatch.setattr(
        cli.oc_ops,
        "ensure_local",
        lambda info, **kwargs: (
            seen.append((info["session_id"], kwargs.get("role", "trigger"))) or False
        ),
    )
    monkeypatch.setattr(cli, "_start_side", lambda *_args, **_kwargs: None)

    cli._apply_resume_legacy("msg")
    assert seen == [("ses_trigger", "trigger"), ("ses_bullet", "bullet")]


def test_resume_stops_loaded_trigger_before_importing_newer_snapshot(monkeypatch):
    data = _dst(server="")
    data["runtime"]["cmd"] = ""
    _patch_resume(monkeypatch, data)
    calls: list[str] = []
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_command",
        lambda name: "opencode" if name == "op_msg" else "zsh",
    )
    monkeypatch.setattr(
        cli.tmux_ops,
        "quit_opencode",
        lambda name: calls.append(f"quit:{name}") or True,
    )

    def ensure(info, **kwargs):
        if info["session_id"] != "ses_trigger":
            return False
        kwargs["prepare_replace"]()
        calls.append("import")
        return True

    monkeypatch.setattr(cli.oc_ops, "ensure_local", ensure)
    monkeypatch.setattr(
        cli,
        "_start_side",
        lambda _data, _tmux, side, *_args: calls.append(f"start:{side}"),
    )

    cli._apply_resume_legacy("msg")

    assert calls == ["quit:op_msg", "import", "start:trigger", "start:bullet"]


def test_claim_rejection_does_not_drop_local_panes(monkeypatch):
    from dual_tmux import hub

    dropped = []
    monkeypatch.setattr(
        hub,
        "claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit("held")),
    )
    monkeypatch.setattr(hub, "drop_local", lambda data: dropped.append(data))
    with pytest.raises(SystemExit, match="held"):
        hub.require_active(_dst())
    assert dropped == []


def test_resume_rebinds_trigger_workspace(monkeypatch, tmp_path):
    data = _dst(server="")
    data["runtime"]["cmd"] = ""
    data["trigger"]["directory"] = "/Users/andy_ouc/.dual-tmux/ops/op_msg"
    _patch_resume(monkeypatch, data)
    launch = tmp_path / "ops" / "op_msg"
    launch.mkdir(parents=True)
    calls: list[str] = []
    monkeypatch.setattr(cli.opsdir, "prepare", lambda _data: launch)
    monkeypatch.setattr(
        cli.oc_ops,
        "by_id",
        lambda _sid: type(
            "S", (), {"directory": "/Users/andy_ouc/.dual-tmux/ops/op_msg"}
        )(),
    )
    monkeypatch.setattr(
        cli.oc_ops,
        "bind_session_directory",
        lambda sid, dest: calls.append(f"bind:{sid}:{dest}") or True,
    )
    monkeypatch.setattr(
        cli.tmux_ops,
        "ensure_session_cwd",
        lambda name, cwd: calls.append(f"cwd:{name}:{cwd}"),
    )
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "zsh")
    monkeypatch.setattr(cli.tmux_ops, "pane_info", lambda _name: {"cwd": str(launch)})
    monkeypatch.setattr(cli.oc_ops, "ensure_local", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        cli,
        "_start_side",
        lambda *_args, **_kwargs: calls.append("start"),
    )
    cli._apply_resume_legacy("msg")
    assert data["trigger"]["directory"] == str(launch)
    assert f"bind:ses_trigger:{launch}" in calls
    assert f"cwd:op_msg:{launch}" in calls
