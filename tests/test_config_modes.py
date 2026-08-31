import json
from argparse import Namespace
from pathlib import Path

import pytest

from dual_tmux import hub
from dual_tmux.cli import build_parser, cmd_config, cmd_new, cmd_pull
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
            workspace="/workspace",
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
