from __future__ import annotations

import argparse
import ast
import inspect
import sys
import textwrap

from dual_tmux import cli
from dual_tmux import tmux as tmux_ops
from dual_tmux.config import AppConfig, init_config, write_config
from dual_tmux.store import find_dt, load, save, tunnels_dir
from dual_tmux.workpoint import empty_point, empty_times


def _handler_names() -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(cli.main)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "handlers"
            for target in node.targets
        ):
            continue
        assert isinstance(node.value, ast.Dict)
        return {
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    raise AssertionError("main() has no handlers mapping")


def test_every_parser_command_has_a_main_dispatch_handler():
    parser = cli.build_parser()
    commands = next(
        action.choices
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert set(commands) == _handler_names()


def test_no_command_runs_readiness_then_enters_latest(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "dt-home"))
    init_config("tm_test", workspace=str(tmp_path))
    calls = []
    monkeypatch.setattr(sys, "argv", ["dt"])
    monkeypatch.setattr(cli, "ensure_ready", lambda: calls.append("ready"))
    monkeypatch.setattr(cli, "cmd_enter", lambda args: calls.append(("enter", args.name)))

    cli.main()

    assert calls == ["ready", ("enter", None)]


def test_no_command_prompts_for_first_time_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "dt-home"))
    calls = []
    monkeypatch.setattr(sys, "argv", ["dt"])
    monkeypatch.setattr(cli, "prompt_init", lambda: calls.append("init"))
    monkeypatch.setattr(cli, "ensure_ready", lambda: calls.append("ready"))
    monkeypatch.setattr(cli, "cmd_enter", lambda args: calls.append(("enter", args.name)))

    cli.main()

    assert calls == ["init", "ready", ("enter", None)]


def test_observation_command_bypasses_config_and_readiness(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "missing-home"))
    calls = []
    monkeypatch.setattr(sys, "argv", ["dt", "ls"])
    monkeypatch.setattr(cli, "prompt_init", lambda: calls.append("init"))
    monkeypatch.setattr(cli, "ensure_ready", lambda: calls.append("ready"))
    monkeypatch.setattr(cli, "cmd_ls", lambda _args: calls.append("ls"))

    cli.main()

    assert calls == ["ls"]


def test_stateful_command_checks_readiness_before_dispatch(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "dt-home"))
    init_config("tm_test", workspace=str(tmp_path))
    calls = []
    monkeypatch.setattr(sys, "argv", ["dt", "new", "demo", "--local"])
    monkeypatch.setattr(cli, "ensure_ready", lambda: calls.append("ready"))
    monkeypatch.setattr(cli, "cmd_new", lambda args: calls.append(("new", args.name)))

    cli.main()

    assert calls == ["ready", ("new", "demo")]


def test_local_new_freeze_drop_resume_keeps_binding_and_sessions(
    monkeypatch, tmp_path
):
    dt_home = tmp_path / "dt-home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("DUAL_TMUX_HOME", str(dt_home))
    init_config("tm_test", workspace=str(workspace))

    ensured = []
    dropped = []
    started = []
    attached = []
    pushes = []
    monkeypatch.setattr(
        cli.tmux_ops,
        "ensure_session",
        lambda name, **kwargs: ensured.append((name, kwargs.get("cwd", ""))),
    )
    monkeypatch.setattr(cli.tmux_ops, "drop_session", lambda name: dropped.append(name) or True)
    monkeypatch.setattr(cli.tmux_ops, "attach", lambda name: attached.append(name))
    monkeypatch.setattr(cli.opsdir, "prepare", lambda _data: tmp_path / "ops")
    monkeypatch.setattr(cli.tmux_ops, "ensure_session_cwd", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli.wp, "discover", lambda name: {"kind": "local", "cwd": str(workspace), "tmux": name})
    monkeypatch.setattr(cli.wp, "canonical_runtime_point", lambda _data, point: point)
    monkeypatch.setattr(cli.oc_ops, "ensure_local", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(cli, "print_inspect", lambda _data: None)
    monkeypatch.setattr(cli.ui, "print_next_new", lambda _name: None)
    monkeypatch.setattr(cli.hub, "push_best_effort", lambda **kwargs: pushes.append(kwargs))
    monkeypatch.setattr(
        cli,
        "_start_side",
        lambda data, tmux_name, side, model, resume: started.append(
            (data["name"], tmux_name, side, model, resume)
        ),
    )

    cli.cmd_new(cli.build_parser().parse_args(["new", "demo", "--local"]))
    created = load(find_dt("demo"))
    assert created["name"] == "dt-demo"
    assert created["runtime"]["server"] == ""
    assert created["runtime"]["directory"] == str(workspace)
    assert [name for name, _cwd in ensured] == ["run_demo", "op_demo"]

    def freeze_sides(data, sides, tool="auto", wait=False):
        assert sides == ["trigger", "bullet"]
        assert tool == "auto"
        assert wait is False
        data["trigger"].update(session_id="trigger-1", slug="trigger", model="m1")
        data["bullet"].update(session_id="bullet-1", slug="bullet", model="m2")

    monkeypatch.setattr(cli, "freeze_sides", freeze_sides)
    cli.cmd_freeze(cli.build_parser().parse_args(["freeze", "demo"]))
    frozen = load(find_dt("demo"))
    assert frozen["trigger"]["session_id"] == "trigger-1"
    assert frozen["bullet"]["session_id"] == "bullet-1"

    cli.cmd_drop(cli.build_parser().parse_args(["drop", "demo"]))
    assert dropped == ["op_demo", "run_demo"]
    assert find_dt("demo").is_file()

    cli.cmd_resume(cli.build_parser().parse_args(["resume", "demo"]))
    assert started == [
        ("dt-demo", "op_demo", "trigger", "", True),
        ("dt-demo", "run_demo", "bullet", "", True),
    ]
    assert attached == ["op_demo"]
    resumed = load(find_dt("demo"))
    assert resumed["trigger"]["session_id"] == "trigger-1"
    assert resumed["bullet"]["session_id"] == "bullet-1"
    assert resumed["times"]["resume_at"]
    assert pushes == [{"wait": True}, {"wait": True}, {}]


def test_hub_drop_releases_and_resume_claims_with_force(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "dt-home"))
    monkeypatch.setenv("OPENCODE_SESSIONS", str(tmp_path / "sessions/opencode"))
    write_config(
        AppConfig(
            client="tm_test",
            server="hub-box",
            user="tester",
            workspace="/workspace",
        )
    )
    side = {
        "tool": "opencode",
        "model": "model",
        "session_id": "session",
        "slug": "slug",
    }
    trigger_side = {**side, "session_id": "trigger-session"}
    bullet_side = {**side, "session_id": "bullet-session"}
    data = {
        "name": "dt-demo",
        "op": "op_demo",
        "run": "run_demo",
        "runtime": {
            "server": "hub-box",
            "directory": "/workspace",
            "cmd": "ssh hub-box",
        },
        "trigger": trigger_side,
        "bullet": bullet_side,
        "op_point": empty_point(),
        "run_point": empty_point(),
        "times": empty_times(),
    }
    save(tunnels_dir() / "dt-demo.json", data)

    ownership = []
    started = []
    monkeypatch.setattr(
        cli.hub,
        "drop_local",
        lambda tunnel: ownership.append(("drop", tunnel["name"])),
    )
    monkeypatch.setattr(
        cli.hub, "release", lambda name: ownership.append(("release", name))
    )
    monkeypatch.setattr(
        cli.hub,
        "require_active",
        lambda tunnel, force=False: ownership.append(
            ("claim", tunnel["name"], force)
        ),
    )
    monkeypatch.setattr(
        "dual_tmux.occupancy.claim_occupancy",
        lambda _name, reason="": {"generation": 1},
    )
    monkeypatch.setattr(cli.opsdir, "prepare", lambda _data: tmp_path / "ops")
    monkeypatch.setattr(cli.tmux_ops, "ensure_session_cwd", lambda *args, **kwargs: True)
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "ssh")
    monkeypatch.setattr(cli.oc_ops, "ensure_local", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        "dual_tmux.recovery.ensure_remote_session", lambda _data: False
    )
    monkeypatch.setattr(
        cli,
        "_start_side",
        lambda _data, tmux_name, target, _model, resume: started.append(
            (tmux_name, target, resume)
        ),
    )
    monkeypatch.setattr(cli.wp, "discover", lambda _name: empty_point())
    monkeypatch.setattr(
        cli.wp, "canonical_runtime_point", lambda _data, point: point
    )
    monkeypatch.setattr(cli.hub, "push_best_effort", lambda **_kwargs: None)
    monkeypatch.setattr(cli.hub, "pull", lambda **_kwargs: None)
    monkeypatch.setattr("dual_tmux.hotfix.sync_ticks", lambda *args, **kwargs: None)
    monkeypatch.setattr("dual_tmux.occupancy.read_occupancy", lambda *_args, **_kwargs: {"generation": 1})
    monkeypatch.setattr(cli, "_preflight_resume_snapshots", lambda _data: None)
    monkeypatch.setattr("dual_tmux.ownership.plan_resume", lambda _data: {
        "schema": 1,
        "name": "dt-demo",
        "safe": True,
        "action": "claim",
        "reason": "free",
        "steps": ["claim", "prepare", "restore", "verify"],
        "ownership": {},
    })
    monkeypatch.setattr(cli.tmux_ops, "attach", lambda _name: None)

    cli.cmd_drop(cli.build_parser().parse_args(["drop", "demo"]))
    cli.cmd_resume(cli.build_parser().parse_args(["resume", "demo", "--force"]))

    assert ownership == [("drop", "dt-demo"), ("release", "dt-demo")]
    assert started == [
        ("op_demo", "trigger", True),
        ("run_demo", "bullet", True),
    ]
    assert find_dt("demo").is_file()


def test_drop_session_detaches_before_kill_so_attached_terminal_returns(monkeypatch):
    calls = []
    monkeypatch.setattr(tmux_ops, "bin", lambda: "tmux")
    monkeypatch.setattr(tmux_ops, "has_session", lambda _name: True)
    monkeypatch.setattr(
        tmux_ops.subprocess,
        "run",
        lambda argv, **_kwargs: calls.append(argv),
    )

    assert tmux_ops.drop_session("op_demo") is True
    assert calls == [
        ["tmux", "detach-client", "-s", "=op_demo"],
        ["tmux", "kill-session", "-t", "=op_demo"],
    ]
