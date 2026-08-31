import json
import subprocess
from pathlib import Path

import pytest

from dual_tmux import agent_sessions

CODEX_ID = "01a05590-bd0f-74d2-8be6-7dd710d9ada5"
CLAUDE_ID = "456f71f3-89ed-4bff-a9c1-6c039a460265"


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _codex(
    home: Path,
    sid: str = CODEX_ID,
    cwd: str = "/workspace",
    stamp: str = "2026-08-31T01:00:01Z",
) -> Path:
    path = home / ".codex" / "sessions" / "2026" / "08" / "31" / f"rollout-{sid}.jsonl"
    _write(
        path,
        [
            {
                "type": "session_meta",
                "timestamp": stamp,
                "payload": {
                    "session_id": sid,
                    "timestamp": stamp,
                    "cwd": cwd,
                    "originator": "codex-tui",
                    "source": "cli",
                },
            }
        ],
    )
    return path


def _claude(
    home: Path,
    sid: str = CLAUDE_ID,
    cwd: str = "/workspace",
    stamp: str = "2026-08-31T01:00:01Z",
) -> Path:
    path = home / ".claude" / "projects" / "-workspace" / f"{sid}.jsonl"
    _write(
        path,
        [
            {"type": "mode", "sessionId": sid},
            {"type": "user", "sessionId": sid, "cwd": cwd, "timestamp": stamp},
        ],
    )
    return path


@pytest.mark.parametrize(
    ("tool", "command", "expected"),
    [
        ("codex", f"codex resume {CODEX_ID}", CODEX_ID),
        ("claude", f"claude --resume {CLAUDE_ID}", CLAUDE_ID),
        ("claude", f"claude --session-id={CLAUDE_ID}", CLAUDE_ID),
    ],
)
def test_explicit_session_id(tool, command, expected):
    assert agent_sessions.explicit_session_id(tool, [command]) == expected


@pytest.mark.parametrize(
    ("tool", "session_id", "expected"),
    [
        ("codex", CODEX_ID, f"codex resume {CODEX_ID}"),
        ("claude", CLAUDE_ID, f"claude --resume {CLAUDE_ID}"),
    ],
)
def test_resume_command_keeps_same_uuid(tool, session_id, expected):
    assert agent_sessions.resume_command(tool, session_id) == expected


def test_native_session_exists_and_remote_probe(tmp_path):
    _codex(tmp_path)
    _claude(tmp_path)
    assert agent_sessions.session_exists("codex", CODEX_ID, home=tmp_path)
    assert agent_sessions.session_exists("claude", CLAUDE_ID, home=tmp_path)
    assert not agent_sessions.session_exists(
        "codex", "01a05590-bd0f-74d2-8be6-7dd710d9ada6", home=tmp_path
    )
    assert CODEX_ID in agent_sessions.remote_session_probe_script("codex", CODEX_ID)
    assert CLAUDE_ID in agent_sessions.remote_session_probe_script("claude", CLAUDE_ID)


def test_codex_explicit_id_wins_and_enriches_from_metadata(tmp_path, monkeypatch):
    _codex(tmp_path)
    monkeypatch.setattr(
        agent_sessions,
        "agent_process",
        lambda *args, **kwargs: (f"codex resume {CODEX_ID}", 1_788_138_000_000),
    )
    got = agent_sessions.discover_local(
        "codex", pid="1", cwd="/workspace", home=tmp_path
    )
    assert got and got.session_id == CODEX_ID
    assert got.directory == "/workspace"


def test_claude_unique_cwd_and_start_time_candidate(tmp_path, monkeypatch):
    _claude(tmp_path)
    monkeypatch.setattr(
        agent_sessions,
        "agent_process",
        lambda *args, **kwargs: ("claude", 1_788_138_000_000),
    )
    got = agent_sessions.discover_local(
        "claude", pid="1", cwd="/workspace", home=tmp_path
    )
    assert got and got.session_id == CLAUDE_ID


def test_old_or_ambiguous_candidates_are_not_bound(tmp_path, monkeypatch):
    _codex(tmp_path, stamp="2026-08-30T01:00:00Z")
    monkeypatch.setattr(
        agent_sessions,
        "agent_process",
        lambda *args, **kwargs: ("codex", 1_788_138_000_000),
    )
    assert (
        agent_sessions.discover_local("codex", pid="1", cwd="/workspace", home=tmp_path)
        is None
    )

    _codex(tmp_path, sid="01a05590-bd0f-74d2-8be6-7dd710d9ada6")
    _codex(tmp_path, sid="01a05590-bd0f-74d2-8be6-7dd710d9ada7")
    assert (
        agent_sessions.discover_local("codex", pid="1", cwd="/workspace", home=tmp_path)
        is None
    )


@pytest.mark.parametrize("container", ["", "work box"])
def test_remote_probe_quotes_ssh_and_docker(container):
    seen = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {"session_id": CODEX_ID, "directory": "/workspace", "tool": "codex"}
            ),
            stderr="",
        )

    got = agent_sessions.discover_remote(
        "codex", ["ssh", "box"], container=container, cwd="/workspace", runner=run
    )
    assert got and got.session_id == CODEX_ID
    assert seen["argv"][:2] == ["ssh", "box"]
    if container:
        assert "docker exec 'work box'" in seen["argv"][-1]
    assert "/workspace" in seen["argv"][-1]


@pytest.mark.parametrize(("tool", "sid"), [("codex", CODEX_ID), ("claude", CLAUDE_ID)])
def test_freeze_native_client_binds_proven_session(tool, sid, monkeypatch):
    from dual_tmux import cli
    from dual_tmux.agentclient import empty
    from dual_tmux.oc import empty_side

    data = {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": empty_side(tool),
        "bullet": empty_side(tool),
        "runtime": {},
    }
    point = {
        "kind": "local",
        "cwd": "/workspace",
        "cmd": tool,
        "ssh": "",
        "container": "",
        "directory": "/workspace",
        "resume_cmd": "",
        "hops": [],
    }
    monkeypatch.setattr(cli.wp, "discover", lambda _name: dict(point))
    monkeypatch.setattr(cli.wp, "walk_commands", lambda _pid: [tool])
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": tool, "cwd": "/workspace"},
    )
    monkeypatch.setattr(
        "dual_tmux.agentclient.collect",
        lambda *args, **kwargs: {
            **empty(),
            "name": tool,
            "version": "1.2.3",
            "location": "local",
        },
    )
    monkeypatch.setattr(
        agent_sessions,
        "discover_local",
        lambda *args, **kwargs: agent_sessions.AgentSession(
            sid, "/workspace", tool=tool
        ),
    )
    monkeypatch.setattr(cli.ev, "emit", lambda *args, **kwargs: None)

    assert cli._freeze_one(data, "trigger", "op_test", "auto", False)
    assert data["trigger"]["tool"] == tool
    assert data["trigger"]["session_id"] == sid
    assert data["trigger"]["directory"] == "/workspace"
    assert data["trigger"]["agent_client"]["version"] == "1.2.3"


def test_start_side_resumes_each_native_client_with_frozen_uuid(monkeypatch):
    from dual_tmux import cli

    data = {
        "trigger": {"tool": "codex", "session_id": CODEX_ID},
        "bullet": {"tool": "claude", "session_id": CLAUDE_ID},
        "runtime": {"directory": "/workspace"},
    }
    sent = []
    monkeypatch.setattr(cli.opsdir, "prepare", lambda _data: Path("/tmp/op_test"))
    monkeypatch.setattr(
        cli.tmux_ops,
        "ensure_agent",
        lambda pane, command, cwd="": sent.append((pane, command, cwd)) or True,
    )

    cli._start_side(data, "op_test", "trigger", resume=True)
    cli._start_side(data, "run_test", "bullet", resume=True)

    assert sent == [
        ("op_test", f"codex resume {CODEX_ID}", "/tmp/op_test"),
        ("run_test", f"claude --resume {CLAUDE_ID}", ""),
    ]


def test_tmux_ensure_agent_recognizes_node_wrapped_codex(monkeypatch):
    from dual_tmux import tmux

    monkeypatch.setattr(tmux, "ensure_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tmux,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": "node", "cwd": "/workspace"},
    )
    monkeypatch.setattr(
        "dual_tmux.workpoint.walk_commands",
        lambda _pid: ["node /opt/lib/@openai/codex/bin/codex.js"],
    )

    assert tmux.ensure_agent("op_test", f"codex resume {CODEX_ID}") is False
