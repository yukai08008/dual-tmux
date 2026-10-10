"""abc (andybot_core) native client: journal discovery, snapshots, patrol."""

import json
import time
from pathlib import Path

import pytest

from dual_tmux import agent_sessions, native_persist, orphan, paneparse

ABC_ID = "20261010-150157"


def _journal(
    home: Path,
    sid: str = ABC_ID,
    started: str = "2026-10-10T15:01:57+00:00",
    extra_rows: list[dict] | None = None,
) -> Path:
    path = home / ".abc" / "sessions" / f"{sid}.jsonl"
    rows: list[dict] = [
        {"row": "message", "data": {"role": "system", "content": "abc runtime"}}
    ]
    if started:
        rows.append(
            {
                "row": "session",
                "data": {
                    "session_id": sid,
                    "journal_path": str(path),
                    "started_at": started,
                },
            }
        )
    rows.extend(extra_rows or [])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_discover_local_binds_explicit_journal_argv(tmp_path, monkeypatch):
    _journal(tmp_path)
    monkeypatch.setattr(
        agent_sessions,
        "agent_process",
        lambda *args, **kwargs: (
            f"abc --resume --journal ~/.abc/sessions/{ABC_ID}.jsonl",
            int(time.time() * 1000),
        ),
    )
    got = agent_sessions.discover_local("abc", pid="1", cwd="/workspace", home=tmp_path)
    assert got and got.session_id == ABC_ID
    assert got.tool == "abc"
    assert got.created_ms > 0


def test_discover_local_binds_unique_fresh_journal_without_cwd(tmp_path, monkeypatch):
    started_ms = int(time.time() * 1000)
    fresh = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(started_ms / 1000))
    _journal(tmp_path, started=fresh)
    monkeypatch.setattr(
        agent_sessions,
        "agent_process",
        lambda *args, **kwargs: ("abc", started_ms),
    )
    got = agent_sessions.discover_local("abc", pid="1", cwd="/workspace", home=tmp_path)
    assert got and got.session_id == ABC_ID


def test_discover_local_refuses_ambiguous_or_old_journals(tmp_path, monkeypatch):
    started_ms = int(time.time() * 1000)
    _journal(tmp_path, started="2026-10-10T15:01:57+00:00")
    _journal(tmp_path, sid=f"{ABC_ID}-2", started="2026-10-10T15:01:58+00:00")
    monkeypatch.setattr(
        agent_sessions,
        "agent_process",
        lambda *args, **kwargs: ("abc", started_ms),
    )
    assert (
        agent_sessions.discover_local("abc", pid="1", cwd="/workspace", home=tmp_path)
        is None
    )

    old = tmp_path / ".abc" / "sessions" / "20260101-000001.jsonl"
    old.write_text(
        json.dumps(
            {
                "row": "session",
                "data": {
                    "session_id": "20260101-000001",
                    "journal_path": str(old),
                    "started_at": "2026-01-01T00:00:00+00:00",
                },
            }
        )
        + "\n"
    )
    assert (
        agent_sessions.discover_local("abc", pid="1", cwd="/workspace", home=tmp_path)
        is None
    )


def test_discover_local_rejects_session_row_mismatch(tmp_path):
    path = tmp_path / ".abc" / "sessions" / f"{ABC_ID}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "row": "session",
                "data": {
                    "session_id": "20260101-000009",
                    "journal_path": str(path),
                    "started_at": "2026-10-10T15:01:57+00:00",
                },
            }
        )
        + "\n"
    )
    assert agent_sessions._abc_record(path) is None


def test_abc_session_exists_and_probe_script(tmp_path):
    _journal(tmp_path)
    assert agent_sessions.session_exists("abc", ABC_ID, home=tmp_path)
    assert not agent_sessions.session_exists("abc", "20991231-235959", home=tmp_path)
    assert not agent_sessions.session_exists("abc", "../../etc/passwd", home=tmp_path)
    probe = agent_sessions.remote_session_probe_script("abc", ABC_ID)
    assert ABC_ID in probe and probe.startswith("python3 -c ")


def test_abc_native_snapshot_roundtrip(tmp_path, monkeypatch):
    source, target, persist = (
        tmp_path / name for name in ("source", "target", "persist")
    )
    original = _journal(source, extra_rows=[
        {"row": "message", "data": {"role": "user", "content": "one"}}
    ])
    info = {
        "tool": "abc",
        "session_id": ABC_ID,
        "directory": "",
        "frozen_at": "2026-10-10T15:05:00+08:00",
        "agent_client": {"version": "0.5.0"},
    }
    active = native_persist.export_session(
        info, "tm_source", source_instance="i-1", generation=3, root=persist, home=source
    )
    assert active and active.name == "active.json"
    manifest = json.loads(active.read_text())
    assert manifest["session_id"] == ABC_ID
    assert manifest["files"][0]["path"] == f"{ABC_ID}.jsonl"
    assert (
        native_persist.export_session(info, "tm_source", root=persist, home=source)
        is None
    )

    assert native_persist.import_session(info, root=persist, home=target)
    found = native_persist.locate_session("abc", ABC_ID, home=target)
    assert found and found.read_bytes() == original.read_bytes()
    assert native_persist.import_session(info, root=persist, home=target) is False


def test_abc_snapshot_detects_live_append(tmp_path):
    source, persist = tmp_path / "source", tmp_path / "persist"
    path = _journal(source, extra_rows=[
        {"row": "message", "data": {"role": "user", "content": "one"}}
    ])
    info = {
        "tool": "abc",
        "session_id": ABC_ID,
        "directory": "",
        "frozen_at": "2026-10-10T15:05:00+08:00",
        "agent_client": {"version": "0.5.0"},
    }
    native_persist.export_session(info, "tm_source", root=persist, home=source)
    assert native_persist.verify_export(
        info, namespace="tm_source", root=persist, home=source
    )
    with path.open("a") as handle:
        handle.write(
            json.dumps(
                {"row": "message", "data": {"role": "assistant", "content": "two"}}
            )
            + "\n"
        )
    assert not native_persist.verify_export(
        info, namespace="tm_source", root=persist, home=source
    )


def test_abc_snapshot_rejects_foreign_journal_content(tmp_path):
    source, target, persist = (
        tmp_path / name for name in ("source", "target", "persist")
    )
    _journal(source)
    native_persist.export_session(
        {
            "tool": "abc",
            "session_id": ABC_ID,
            "directory": "",
            "frozen_at": "2026-10-10T15:05:00+08:00",
            "agent_client": {},
        },
        "tm_source",
        root=persist,
        home=source,
    )
    active = persist / "tm_source" / "abc" / ABC_ID / "active.json"
    manifest = json.loads(active.read_text())
    payload = (
        active.parent
        / "revisions"
        / manifest["revision"]
        / "payload"
        / f"{ABC_ID}.jsonl"
    )
    rows = [json.loads(line) for line in payload.read_text().splitlines() if line]
    rows[1]["data"]["session_id"] = "20260101-000001"
    payload.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(SystemExit, match="mismatch"):
        native_persist.import_session(
            {
                "tool": "abc",
                "session_id": ABC_ID,
                "directory": "",
                "frozen_at": "2026-10-10T15:05:00+08:00",
                "agent_client": {},
            },
            root=persist,
            home=target,
        )


def test_orphan_scan_filters_abc_processes_by_boundary():
    assert orphan._is_agent_process(
        "abc --resume --journal /root/.abc/sessions/20261010-150157.jsonl "
    )
    assert orphan._is_agent_process("python3 /usr/local/bin/abc ")
    assert orphan._is_agent_process("/root/.local/bin/abc")
    assert orphan._is_agent_process(
        "/uv/tools/andybot-core/bin/python3 /usr/local/bin/abc"
    )
    assert not orphan._is_agent_process("vim /tmp/abc.txt")
    assert not orphan._is_agent_process("tail -f /root/.abc/history")
    assert not orphan._is_agent_process("grep abcdef file")


def test_abc_pane_parser_phases():
    idle = paneparse.parse_pane(
        "任务已完成，交付如下。\n│ \n└────────┘\n glm-5 · session 20261010-150157 · /help",
        "abc",
    )
    assert idle.parser == "abc@1"
    assert idle.phase == "idle"
    assert idle.completion_id
    assert "session 20261010" not in idle.body
    assert "任务已完成" in idle.body

    running = paneparse.parse_pane("正在分析代码\n⠋ 思考中", "abc")
    assert running.phase == "running"
    assert running.completion_id == ""
    assert "正在分析代码" in running.body


def test_abc_client_detection_and_probe():
    from dual_tmux import agentclient
    from dual_tmux.agents import get_adapter

    assert agentclient.normalize_name("abc") == "abc"
    assert agentclient.detect_name(["python3 /usr/local/bin/abc --resume"]) == "abc"
    assert get_adapter("abc") is not None
