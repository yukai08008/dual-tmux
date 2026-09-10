import json
from argparse import Namespace
from pathlib import Path

import pytest

from dual_tmux import cli, hub
from dual_tmux.cli import build_parser, cmd_config, cmd_new, cmd_pull, cmd_tick
from dual_tmux.config import (
    AppConfig,
    _parse_toml,
    init_config,
    load_config,
    make_config,
    switch_config,
    write_config,
)
from dual_tmux.health import collect_checks
from dual_tmux.runtime import build_cmd
from dual_tmux.store import save, tunnels_dir


def _home(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "dt-home"
    monkeypatch.setenv("DUAL_TMUX_HOME", str(root))
    return root


def test_local_config_round_trip_and_legacy_hub_compatibility(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    path = init_config("tm_laptop", workspace=str(tmp_path))
    assert load_config() == AppConfig(client="tm_laptop", workspace=str(tmp_path))
    assert path.read_text() == f'client = "tm_laptop"\nworkspace = "{tmp_path}"\n'

    legacy = _parse_toml('client = "tm_laptop"\nserver = "tom7r"\nuser = "andy"\n')
    assert legacy.hub_enabled
    assert legacy.mode == "hub"


@pytest.mark.parametrize(
    ("server", "user"),
    [("tom7r", ""), ("", "andy")],
)
def test_partial_hub_config_is_rejected(monkeypatch, tmp_path, server, user):
    _home(monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="set together"):
        init_config("tm_laptop", server, user)


def test_attach_replace_and_detach_merge_before_commit(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        hub, "sync", lambda cfg: calls.append((cfg.server, cfg.user)) or cfg.server
    )

    local = make_config("tm_laptop", workspace=str(tmp_path))
    write_config(local)
    first = make_config("tm_laptop", "hub-a", "andy", str(tmp_path))
    switch_config(local, first)
    assert calls == [("hub-a", "andy")]
    assert load_config().server == "hub-a"

    calls.clear()
    second = make_config("tm_laptop", "hub-b", "andy", str(tmp_path))
    switch_config(first, second)
    assert calls == [("hub-a", "andy"), ("hub-b", "andy")]
    assert load_config().server == "hub-b"

    calls.clear()
    switch_config(second, local)
    assert calls == [("hub-b", "andy")]
    assert load_config().mode == "local"


def test_failed_candidate_sync_keeps_old_config(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    old = make_config("tm_laptop", "hub-a", "andy")
    write_config(old)
    before = (tmp_path / "dt-home" / "config.toml").read_bytes()

    def sync(cfg):
        if cfg.server == "hub-b":
            raise SystemExit("candidate unavailable")
        return cfg.server

    monkeypatch.setattr(hub, "sync", sync)
    with pytest.raises(SystemExit, match="candidate unavailable"):
        switch_config(old, make_config("tm_laptop", "hub-b", "andy"))
    assert (tmp_path / "dt-home" / "config.toml").read_bytes() == before
    assert load_config().server == "hub-a"


def test_local_hub_background_helpers_do_not_touch_network(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    init_config("tm_laptop", workspace=str(tmp_path))
    monkeypatch.setattr(
        hub, "push", lambda *_args, **_kwargs: pytest.fail("network push")
    )
    monkeypatch.setattr(
        hub, "sync", lambda *_args, **_kwargs: pytest.fail("network sync")
    )
    hub.push_best_effort(wait=True)
    hub.sync_best_effort(wait=True)
    assert hub.claim("dt-local") == "tm_laptop"
    assert hub.read_lock("dt-local") == ("", 0)


def test_explicit_pull_in_local_mode_is_actionable(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    init_config("tm_laptop", workspace=str(tmp_path))
    with pytest.raises(SystemExit, match="dt config --server"):
        cmd_pull(Namespace())


def test_pull_syncs_persist_snapshots(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    write_config(make_config("tm_laptop", "hub-a", "andy", str(tmp_path)))
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(hub, "pull", lambda: "hub-a")
    monkeypatch.setattr(
        cli.hotfix_ops,
        "sync_persist",
        lambda kind, cfg, **_k: calls.append((kind, cfg.server)),
    )
    monkeypatch.setattr(cli.statusbar, "refresh", lambda _items: None)

    cmd_pull(Namespace())

    assert calls == [
        ("opencode", "hub-a"),
        ("tmux", "hub-a"),
        ("native", "hub-a"),
    ]


def test_tick_immediately_syncs_changed_native_snapshot(monkeypatch, tmp_path):
    from dual_tmux import activity, feishu_bridge, recovery, statusbar

    _home(monkeypatch, tmp_path)
    cfg = make_config("tm_laptop", "hub-a", "andy", str(tmp_path))
    write_config(cfg)
    save(
        tunnels_dir() / "dt-a.json",
        {
            "name": "dt-a",
            "op": "op_a",
            "run": "run_a",
            "runtime": {},
            "trigger": {"tool": "codex"},
            "bullet": {"tool": "opencode"},
        },
    )
    monkeypatch.setattr(hub, "enforce_local", lambda: None)
    monkeypatch.setattr(
        hub,
        "read_ownership",
        lambda *_a, **_kw: {"state": "owned", "holder": "tm_laptop"},
    )
    monkeypatch.setattr(
        hub, "claim", lambda _name: pytest.fail("tick must not claim ownership")
    )
    monkeypatch.setattr(hub, "sync_best_effort", lambda **_kw: None)
    monkeypatch.setattr(cli.tmux_ops, "has_session", lambda _name: True)
    monkeypatch.setattr(activity, "append_sample", lambda _data: None)
    monkeypatch.setattr(activity, "activity_evidence", lambda _data: {})
    monkeypatch.setattr(activity, "activity_path", lambda: tmp_path / "activity.log")
    monkeypatch.setattr(recovery, "observe", lambda _data: {})
    monkeypatch.setattr(statusbar, "refresh", lambda *_a, **_kw: None)
    monkeypatch.setattr(feishu_bridge, "sync_client", lambda _cfg: {})
    monkeypatch.setattr(cli, "_export_local_snapshots", lambda *_a: [])
    calls = []
    monkeypatch.setattr(
        cli.hotfix_ops,
        "sync_persist",
        lambda kind, used_cfg: calls.append((kind, used_cfg.server)),
    )

    cmd_tick(Namespace())

    assert calls == [("native", "hub-a")]


def test_local_health_has_no_ssh_check(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    init_config("tm_laptop", workspace=str(tmp_path))
    monkeypatch.setattr("dual_tmux.health.tmux_ops.have_tmux", lambda: True)
    monkeypatch.setattr("dual_tmux.health.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr("dual_tmux.cron.installed", lambda: True)
    _, checks = collect_checks()
    assert next(row for row in checks if row.label == "mode").detail == "local-only"
    assert not any(row.label == "ssh server" for row in checks)


def test_config_cli_exposes_local_and_prints_mode(monkeypatch, tmp_path, capsys):
    _home(monkeypatch, tmp_path)
    assert (
        "--local" in build_parser().format_help()
        or "--local"
        in build_parser()._subparsers._group_actions[0].choices["config"].format_help()
    )
    init_config("tm_laptop", workspace=str(tmp_path))
    cmd_config(
        Namespace(
            init=False,
            local=False,
            client="",
            server="",
            user="",
            workspace="",
        )
    )
    assert "local" in capsys.readouterr().out


def test_local_runtime_commands():
    assert build_cmd("", "", "/tmp/a b") == "cd '/tmp/a b'"


def test_new_local_tunnel_has_no_ssh_runtime(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    init_config("tm_laptop", workspace=str(tmp_path))
    monkeypatch.setattr(
        "dual_tmux.cli.tmux_ops.ensure_session", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr("dual_tmux.cli.opsdir.prepare", lambda _data: tmp_path)
    monkeypatch.setattr("dual_tmux.cli.print_inspect", lambda _data: None)
    monkeypatch.setattr("dual_tmux.cli.ui.print_next_new", lambda _name: None)
    cmd_new(
        Namespace(
            name="local",
            op=None,
            run=None,
            server="",
            container="",
            dir="",
            cmd="",
        )
    )
    data = json.loads((tmp_path / "dt-home" / "tunnels" / "dt-local.json").read_text())
    assert data["runtime"]["server"] == ""
    assert data["runtime"]["cmd"] == f"cd {tmp_path}"


def test_config_switch_changes_only_the_default_workspace(monkeypatch, tmp_path):
    _home(monkeypatch, tmp_path)
    local = make_config("tm_laptop", workspace=str(tmp_path))
    write_config(local)
    monkeypatch.setattr(hub, "sync", lambda _cfg: "ok")
    monkeypatch.setattr("dual_tmux.cli._run_hotfix", lambda *_args, **_kwargs: None)

    cmd_config(
        Namespace(
            init=False,
            local=False,
            client="",
            server="tom7r",
            user="andy",
            workspace="",
        )
    )
    assert load_config().workspace == "/workspace"

    monkeypatch.chdir(tmp_path)
    cmd_config(
        Namespace(
            init=False,
            local=True,
            client="",
            server="",
            user="",
            workspace="",
        )
    )
    assert load_config().workspace == str(tmp_path)


def test_bare_tunnel_name_is_resume():
    parser = build_parser()
    argv = cli._argv_with_tunnel_resume(["dt-andy-q"], parser)
    args = parser.parse_args(argv)
    assert argv == ["resume", "dt-andy-q"]
    assert args.command == "resume"
    assert args.name == "dt-andy-q"


def test_known_command_is_not_rewritten_to_resume():
    parser = build_parser()
    assert cli._argv_with_tunnel_resume(["ls"], parser) == ["ls"]
    assert cli._argv_with_tunnel_resume(["resume", "dt-andy-q"], parser) == [
        "resume",
        "dt-andy-q",
    ]
