from argparse import Namespace
from pathlib import Path

from dual_tmux import cli, tmux


def test_ensure_session_cwd_creates_new_pane_at_requested_path(monkeypatch, tmp_path):
    target = tmp_path / "ops" / "op_gate"
    calls = []
    monkeypatch.setattr(
        tmux,
        "ensure_session",
        lambda name, cwd="": calls.append((name, cwd)),
    )
    monkeypatch.setattr(
        tmux,
        "pane_info",
        lambda _name: {"cmd": "zsh", "cwd": str(target)},
    )

    assert tmux.ensure_session_cwd("op_gate", str(target))
    assert calls == [("op_gate", str(target))]


def test_ensure_session_cwd_aligns_existing_idle_shell(monkeypatch, tmp_path):
    target = tmp_path / "ops" / "op_gate"
    state = {"cwd": "/Users/andy"}
    sent = []
    monkeypatch.setattr(tmux, "ensure_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tmux,
        "pane_info",
        lambda _name: {"cmd": "zsh", "cwd": state["cwd"]},
    )

    def run(argv, **_kwargs):
        sent.append(argv)
        if "cd " in argv[-2]:
            state["cwd"] = str(target)

    monkeypatch.setattr(tmux.subprocess, "run", run)
    monkeypatch.setattr(tmux, "bin", lambda: "tmux")

    assert tmux.ensure_session_cwd("op_gate", str(target))
    assert sent == [
        ["tmux", "send-keys", "-t", "=op_gate:", "C-c"],
        ["tmux", "send-keys", "-t", "=op_gate:", "--", f"cd {target}", "Enter"]
    ]


def test_ensure_session_cwd_preserves_running_foreground_program(monkeypatch):
    monkeypatch.setattr(tmux, "ensure_session", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tmux,
        "pane_info",
        lambda _name: {"cmd": "opencode", "cwd": "/Users/andy"},
    )
    monkeypatch.setattr(
        tmux.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not inject cd into a foreground program")
        ),
    )

    assert not tmux.ensure_session_cwd("op_gate", "/tmp/ops/op_gate")


def test_plain_enter_establishes_workdir_before_discover_and_attach(monkeypatch):
    data = {"name": "dt-gate", "op": "op_gate"}
    launch = Path("/tmp/ops/op_gate")
    calls = []
    monkeypatch.setattr(cli, "_resolve", lambda _name: data)
    monkeypatch.setattr(cli.hub, "require_active", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli.opsdir, "prepare", lambda _data: launch)
    monkeypatch.setattr(
        cli.tmux_ops,
        "ensure_session_cwd",
        lambda name, cwd: calls.append(("cwd", name, cwd)) or True,
    )
    monkeypatch.setattr(cli.ev, "emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli.wp, "stamp", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "_touch_point",
        lambda _data, side: calls.append(("discover", side)),
    )
    monkeypatch.setattr(
        cli.tmux_ops,
        "attach",
        lambda name: calls.append(("attach", name)),
    )

    cli.cmd_enter(
        Namespace(name="dt-gate", force=False, oc=False, resume=False, model="")
    )

    assert calls == [
        ("cwd", "op_gate", str(launch)),
        ("discover", "op"),
        ("attach", "op_gate"),
    ]
