import json
from pathlib import Path

import pytest

from dual_tmux import native_persist

CODEX_ID = "01a05590-bd0f-74d2-8be6-7dd710d9ada5"
CLAUDE_ID = "456f71f3-89ed-4bff-a9c1-6c039a460265"


def _append(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _session(home: Path, tool: str, sid: str, extra: str = "") -> Path:
    if tool == "codex":
        path = home / ".codex/sessions/2026/09/07" / f"rollout-{sid}.jsonl"
        rows = [
            {
                "type": "session_meta",
                "payload": {"session_id": sid, "cwd": "/workspace", "source": "cli"},
            }
        ]
        if extra:
            rows.append({"type": "event_msg", "payload": {"message": extra}})
    else:
        path = home / ".claude/projects/-workspace" / f"{sid}.jsonl"
        rows = [{"type": "user", "sessionId": sid, "cwd": "/workspace"}]
        if extra:
            rows.append({"type": "assistant", "sessionId": sid, "message": extra})
    _append(path, rows)
    return path


def _info(tool: str, sid: str) -> dict:
    return {
        "tool": tool,
        "session_id": sid,
        "directory": "/workspace",
        "frozen_at": "2026-09-07T10:00:00+08:00",
        "agent_client": {"version": "1.2.3"},
    }


@pytest.mark.parametrize(("tool", "sid"), [("codex", CODEX_ID), ("claude", CLAUDE_ID)])
def test_exact_uuid_export_and_idempotent_import(tmp_path, tool, sid):
    source = tmp_path / "source"
    target = tmp_path / "target"
    persist = tmp_path / "persist"
    original = _session(source, tool, sid, "one")
    _session(source, tool, "11111111-1111-4111-8111-111111111111", "private-other")

    active = native_persist.export_session(
        _info(tool, sid),
        "tm_source",
        source_instance="i-1",
        generation=7,
        root=persist,
        home=source,
    )
    assert active and active.name == "active.json"
    assert (
        native_persist.export_session(
            _info(tool, sid), "tm_source", root=persist, home=source
        )
        is None
    )
    manifest = json.loads(active.read_text())
    assert manifest["session_id"] == sid
    assert manifest["generation"] == 7
    assert manifest["agent_client_version"] == "1.2.3"
    assert len(manifest["files"]) == 1
    assert "11111111-1111-4111-8111-111111111111" not in "".join(
        str(path) for path in persist.rglob("*")
    )

    assert native_persist.import_session(_info(tool, sid), root=persist, home=target)
    found = native_persist.locate_session(tool, sid, home=target)
    assert found and found.read_bytes() == original.read_bytes()
    assert (
        native_persist.import_session(_info(tool, sid), root=persist, home=target)
        is False
    )


def test_newer_append_replaces_with_backup(tmp_path, monkeypatch):
    source, target, persist = (
        tmp_path / name for name in ("source", "target", "persist")
    )
    src = _session(source, "codex", CODEX_ID, "one")
    _session(target, "codex", CODEX_ID, "one")
    native_persist.export_session(
        _info("codex", CODEX_ID), "tm_source", root=persist, home=source
    )
    _append(src, [{"type": "event_msg", "payload": {"message": "two"}}])
    native_persist.export_session(
        _info("codex", CODEX_ID), "tm_source", root=persist, home=source
    )
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "dt-home"))
    assert native_persist.import_session(
        _info("codex", CODEX_ID), root=persist, home=target
    )
    assert (
        "two"
        in native_persist.locate_session("codex", CODEX_ID, home=target).read_text()
    )
    assert (
        len(
            list((tmp_path / "dt-home/native-backups/codex" / CODEX_ID).glob("*.jsonl"))
        )
        == 1
    )


def test_divergence_and_truncated_payload_fail_closed(tmp_path):
    source, target, persist = (
        tmp_path / name for name in ("source", "target", "persist")
    )
    _session(source, "claude", CLAUDE_ID, "source")
    local = _session(target, "claude", CLAUDE_ID, "target")
    active = native_persist.export_session(
        _info("claude", CLAUDE_ID), "tm_source", root=persist, home=source
    )
    before = local.read_bytes()
    with pytest.raises(SystemExit, match="diverged"):
        native_persist.import_session(
            _info("claude", CLAUDE_ID), root=persist, home=target
        )
    assert local.read_bytes() == before

    local.unlink()
    manifest = json.loads(active.read_text())
    relative = Path(manifest["files"][0]["path"])
    payload = active.parent / "revisions" / manifest["revision"] / "payload" / relative
    payload.write_bytes(payload.read_bytes() + b'{"broken"')
    with pytest.raises(SystemExit, match="truncated JSONL"):
        native_persist.import_session(
            _info("claude", CLAUDE_ID), root=persist, home=target
        )
    assert native_persist.locate_session("claude", CLAUDE_ID, home=target) is None


def test_generation_change_never_commits(tmp_path):
    source, target, persist = (
        tmp_path / name for name in ("source", "target", "persist")
    )
    _session(source, "codex", CODEX_ID, "one")
    native_persist.export_session(
        _info("codex", CODEX_ID), "tm_source", root=persist, home=source
    )
    checks = []

    def fence():
        checks.append(1)
        if len(checks) == 3:
            raise SystemExit("generation changed")

    with pytest.raises(SystemExit, match="generation changed"):
        native_persist.import_session(
            _info("codex", CODEX_ID), root=persist, home=target, generation_check=fence
        )
    assert native_persist.locate_session("codex", CODEX_ID, home=target) is None


def test_unfrozen_and_invalid_source_are_rejected(tmp_path):
    _session(tmp_path, "codex", CODEX_ID)
    info = _info("codex", CODEX_ID)
    info.pop("frozen_at")
    assert native_persist.export_session(info, "tm_source", home=tmp_path) is None
    with pytest.raises(SystemExit, match="source Client"):
        native_persist.export_session(
            _info("codex", CODEX_ID), "../escape", home=tmp_path
        )


def test_persist_namespace_can_differ_from_client_identity(tmp_path):
    _session(tmp_path / "home", "codex", CODEX_ID)
    active = native_persist.export_session(
        _info("codex", CODEX_ID),
        "tm_ouc",
        namespace="tm_andy_ouc",
        root=tmp_path / "persist",
        home=tmp_path / "home",
    )
    assert active.relative_to(tmp_path / "persist").parts[0] == "tm_andy_ouc"
    assert json.loads(active.read_text())["source_client"] == "tm_ouc"


def test_manifest_traversal_and_payload_symlink_are_rejected(tmp_path):
    source, target, persist = (
        tmp_path / name for name in ("source", "target", "persist")
    )
    original = _session(source, "codex", CODEX_ID)
    active = native_persist.export_session(
        _info("codex", CODEX_ID), "tm_source", root=persist, home=source
    )
    manifest = json.loads(active.read_text())
    sealed = active.parent / "revisions" / manifest["revision"] / "manifest.json"
    manifest["revision"] = "../../outside"
    active.write_text(json.dumps(manifest))
    with pytest.raises(SystemExit, match="revision is invalid"):
        native_persist.import_session(
            _info("codex", CODEX_ID), root=persist, home=target
        )

    active.write_text(sealed.read_text())
    manifest = json.loads(active.read_text())
    relative = Path(manifest["files"][0]["path"])
    payload = active.parent / "revisions" / manifest["revision"] / "payload" / relative
    payload.unlink()
    payload.symlink_to(original)
    with pytest.raises(SystemExit, match="escaped its revision|not a regular file"):
        native_persist.import_session(
            _info("codex", CODEX_ID), root=persist, home=target
        )


def test_verify_export_detects_live_append(tmp_path):
    source, persist = tmp_path / "source", tmp_path / "persist"
    path = _session(source, "claude", CLAUDE_ID, "one")
    native_persist.export_session(
        _info("claude", CLAUDE_ID), "tm_source", root=persist, home=source
    )
    assert native_persist.verify_export(
        _info("claude", CLAUDE_ID),
        namespace="tm_source",
        root=persist,
        home=source,
    )
    _append(path, [{"type": "assistant", "sessionId": CLAUDE_ID, "message": "two"}])
    assert not native_persist.verify_export(
        _info("claude", CLAUDE_ID),
        namespace="tm_source",
        root=persist,
        home=source,
    )
