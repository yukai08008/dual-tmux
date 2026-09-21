from __future__ import annotations

import argparse
import json
from pathlib import Path

from datanode.adapters import from_legacy_tunnel, to_legacy_tunnel
from dual_tmux import cli, web
from dual_tmux.config import AppConfig, write_config
from dual_tmux.paths import tunnels_dir
from dual_tmux.store import find_dt, load, save
from dual_tmux.ui import print_ls


def _write_tunnel(root: Path, name: str, extra: dict | None = None) -> Path:
    path = root / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "name": name,
        "op": f"op_{name[3:]}",
        "run": f"run_{name[3:]}",
        "updated_at": "2026-09-18T12:00:00+08:00",
    }
    record.update(extra or {})
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_adapters_map_description_with_empty_default():
    node = from_legacy_tunnel(
        {"name": "dt-demo", "op": "op_demo", "run": "run_demo"}
    )
    assert node.description == ""

    node = from_legacy_tunnel(
        {
            "name": "dt-demo",
            "op": "op_demo",
            "run": "run_demo",
            "description": "新闻解读流水线",
        }
    )
    assert node.description == "新闻解读流水线"

    fresh = to_legacy_tunnel(node)
    assert fresh["description"] == "新闻解读流水线"


def test_to_legacy_without_description_keeps_old_records_key_free():
    record = {
        "name": "dt-demo",
        "op": "op_demo",
        "run": "run_demo",
        "legacy_extra": "keep-me",
    }
    node = from_legacy_tunnel(record)
    roundtrip = to_legacy_tunnel(node, base=record)
    assert "description" not in roundtrip
    assert roundtrip["legacy_extra"] == "keep-me"


def test_save_roundtrip_survives_tick_style_rewrite(tmp_path, monkeypatch):
    """红线：tick/daemon 式 load→改键→save 不得丢 description。"""
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    path = _write_tunnel(
        tunnels_dir(), "dt-msg", {"description": " alex-serp 检索隧道"}
    )

    data = load(path)
    data["updated_at"] = "2026-09-21T09:00:00+08:00"
    save(path, data)

    reloaded = load(path)
    assert reloaded["description"] == " alex-serp 检索隧道"


def test_new_desc_option_writes_registry(tmp_path, monkeypatch):
    from dual_tmux.config import init_config

    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    init_config("tm_laptop", workspace=str(tmp_path))
    monkeypatch.setattr(
        "dual_tmux.cli.tmux_ops.ensure_session", lambda *_a, **_k: None
    )
    monkeypatch.setattr("dual_tmux.cli.opsdir.prepare", lambda _data: tmp_path)
    monkeypatch.setattr("dual_tmux.cli.print_inspect", lambda _data: None)
    monkeypatch.setattr("dual_tmux.cli.ui.print_next_new", lambda _name: None)

    cli.cmd_new(
        argparse.Namespace(
            name="descd",
            op=None,
            run=None,
            server="",
            container="",
            dir="",
            cmd="",
            desc=" 语义描述冒烟 ",
        )
    )
    data = load(find_dt("dt-descd"))
    assert data["description"] == "语义描述冒烟"

    cli.cmd_new(
        argparse.Namespace(
            name="plain",
            op=None,
            run=None,
            server="",
            container="",
            dir="",
            cmd="",
            desc="",
        )
    )
    plain = load(find_dt("dt-plain"))
    assert "description" not in plain


def test_desc_command_sets_updates_and_prints(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    pushes: list[bool] = []
    monkeypatch.setattr(
        "dual_tmux.cli.hub.push_best_effort", lambda wait=False: pushes.append(wait)
    )
    _write_tunnel(tunnels_dir(), "dt-msg")

    cli.cmd_desc(
        argparse.Namespace(name="dt-msg", text="新闻事件 trigger→bullet")
    )
    assert load(find_dt("dt-msg"))["description"] == "新闻事件 trigger→bullet"
    assert pushes == [True]
    assert capsys.readouterr().out.strip() == "新闻事件 trigger→bullet"

    cli.cmd_desc(argparse.Namespace(name="msg", text=""))
    assert capsys.readouterr().out.strip() == "新闻事件 trigger→bullet"
    assert pushes == [True]

    _write_tunnel(tunnels_dir(), "dt-bare")
    cli.cmd_desc(argparse.Namespace(name="dt-bare", text=""))
    assert capsys.readouterr().out.strip() == "—"


def test_print_ls_description_column_set_unset_and_truncated(capsys):
    long_desc = "跨机器语义描述超长版本" * 8
    print_ls(
        [
            {"name": "dt-a", "op": "op_a", "run": "run_a", "description": "简短语义"},
            {"name": "dt-b", "op": "op_b", "run": "run_b"},
            {"name": "dt-c", "op": "op_c", "run": "run_c", "description": long_desc},
        ]
    )
    out = capsys.readouterr().out
    assert "DESCRIPTION" in out
    assert "简短语义" in out
    assert "…" in out
    assert long_desc not in out


def test_web_rows_dashboard_and_detail_carry_description(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    save(
        tunnels_dir() / "dt-msg.json",
        {"name": "dt-msg", "op": "op_msg", "run": "run_msg", "description": "dt 隧道语义"},
    )

    rows = web._tunnels()
    assert rows[0]["description"] == "dt 隧道语义"

    from dual_tmux.web_pages import dashboard_page

    assert "dt 隧道语义" in dashboard_page()


def test_legacy_fixture_tunnel_stays_description_free(tmp_path, monkeypatch):
    import shutil

    fixture = Path(__file__).parent / "fixtures" / "legacy-v0.4.39"
    home = tmp_path / "dt-home"
    shutil.copytree(fixture, home)
    monkeypatch.setenv("DUAL_TMUX_HOME", str(home))

    path = find_dt("dt-legacy")
    data = load(path)
    assert "description" not in data
    save(path, data)
    assert "description" not in load(path)
