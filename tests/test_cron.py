import json
import sys

import pytest

from dual_tmux import cli, cron
from dual_tmux import tmux as tmux_ops


def test_cron_line_carries_path():
    line = cron.line()
    assert "PATH=" in line
    assert "/opt/homebrew/bin" in line
    assert " tick " in line
    assert line.startswith("* * * * * ")


def test_install_replaces_legacy_line(monkeypatch):
    legacy = "* * * * * /Users/x/.local/bin/dt tick >/dev/null 2>&1"
    other = "* * * * * /Users/x/.dual-tmux/bin/dt-persist-tmux >/dev/null 2>&1"
    written = []

    class R:
        returncode = 0
        stdout = f"{legacy}\n{other}\n"
        stderr = ""

    def run(cmd, **kwargs):
        if cmd == ["crontab", "-"]:
            written.append(kwargs.get("input") or "")
            return R()
        return R()

    monkeypatch.setattr(cron.subprocess, "run", run)
    assert cron.install() is True
    body = written[0]
    assert legacy not in body
    assert other in body
    assert cron.line() in body
    assert body.count("dt tick") == 1


def test_install_noop_when_current(monkeypatch):
    class R:
        returncode = 0
        stdout = cron.line() + "\n"
        stderr = ""

    monkeypatch.setattr(cron.subprocess, "run", lambda *a, **k: R())
    assert cron.install() is False


def test_tmux_bin_fallbacks(monkeypatch):
    monkeypatch.setattr(tmux_ops.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        tmux_ops.os.path, "isfile", lambda p: p == "/opt/homebrew/bin/tmux"
    )
    monkeypatch.setattr(tmux_ops.os, "access", lambda p, m: True)
    assert tmux_ops.bin() == "/opt/homebrew/bin/tmux"
    assert tmux_ops.have_tmux() is True


def test_tmux_bin_missing(monkeypatch):
    monkeypatch.setattr(tmux_ops.shutil, "which", lambda _name: None)
    monkeypatch.setattr(tmux_ops.os.path, "isfile", lambda p: False)
    assert tmux_ops.have_tmux() is False


def test_main_emits_cmd_fail_on_unhandled_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["dt", "ls"])

    def boom(_args):
        raise RuntimeError("tick blew up")

    monkeypatch.setattr(cli, "cmd_ls", boom)
    with pytest.raises(RuntimeError):
        cli.main()
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    fails = [e for e in events if e.get("kind") == "cmd.fail"]
    assert len(fails) == 1
    assert "tick blew up" in fails[0]["error"]
    assert not [e for e in events if e.get("kind") == "cmd.ok"]


def test_hotfix_install_tick_refreshes_stale_line(monkeypatch):
    from dual_tmux import hotfix

    calls = []
    monkeypatch.setattr(
        hotfix.cron_ops,
        "current",
        lambda: "* * * * * /Users/x/.local/bin/dt tick >/dev/null 2>&1\n",
    )
    monkeypatch.setattr(
        hotfix.cron_ops, "install", lambda: calls.append("install") or True
    )
    step = hotfix.install_tick()
    assert step.changed is True
    assert calls == ["install"]

    monkeypatch.setattr(hotfix.cron_ops, "current", lambda: cron.line() + "\n")
    calls.clear()
    step = hotfix.install_tick()
    assert step.changed is False
    assert calls == []
