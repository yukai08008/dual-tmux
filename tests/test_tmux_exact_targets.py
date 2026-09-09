from __future__ import annotations

import subprocess

from dual_tmux import tmux


def test_has_session_disables_tmux_prefix_matching(monkeypatch):
    calls: list[list[str]] = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(tmux, "bin", lambda: "tmux")
    monkeypatch.setattr(tmux.subprocess, "run", run)

    assert tmux.has_session("op_a") is False
    assert calls == [["tmux", "has-session", "-t", "=op_a"]]


def test_drop_does_not_kill_a_prefix_match(monkeypatch):
    calls: list[list[str]] = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(tmux, "bin", lambda: "tmux")
    monkeypatch.setattr(tmux.subprocess, "run", run)

    assert tmux.drop_session("run_a") is False
    assert calls == [["tmux", "has-session", "-t", "=run_a"]]


def test_destructive_targets_are_exact(monkeypatch):
    calls: list[list[str]] = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(tmux, "bin", lambda: "tmux")
    monkeypatch.setattr(tmux.subprocess, "run", run)

    assert tmux.drop_session("op_a") is True
    assert [call[3] for call in calls] == ["=op_a", "=op_a", "=op_a", "=op_a"]
