import json
from pathlib import Path

import pytest

from dual_tmux.identity import (
    persist_hub_kind,
    persist_local_kind,
    persist_rsync_rel,
    persist_source_dir,
    remote_dt_root,
    remote_sessions_root,
)
from dual_tmux.oc import ensure_local, persist_snapshot


def test_tenant_paths_not_login_home():
    assert remote_sessions_root("andy") == "~/andy/sessions"
    assert remote_dt_root("andy") == "~/andy/dual-tmux"
    assert persist_local_kind("opencode") == "~/sessions/opencode"
    assert persist_local_kind("tmux") == "~/sessions/tmux"
    assert persist_hub_kind("andy", "opencode") == "~/andy/sessions/opencode"
    assert persist_hub_kind("andy", "tmux") == "~/andy/sessions/tmux"
    assert persist_rsync_rel("andy", "opencode") == "andy/sessions/opencode"
    assert persist_source_dir("opencode", "tm_andy_home") == "~/sessions/opencode/tm_andy_home"
    assert persist_source_dir("opencode", "tm_ouc", hub_user="andy") == "~/andy/sessions/opencode/tm_ouc"
    with pytest.raises(ValueError):
        persist_rsync_rel("tm_andy", "opencode")
    with pytest.raises(ValueError):
        persist_source_dir("opencode", "andy_messenger")
    with pytest.raises(ValueError):
        persist_hub_kind("andy", "docker")


def _write_json(path: Path, session_id: str, slug: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"info": {"id": session_id, "slug": slug, "title": slug}}),
        encoding="utf-8",
    )


def test_snapshot_ignores_container_named_dirs(tmp_path: Path):
    root = tmp_path / "sessions" / "opencode"
    _write_json(root / "andy_messenger" / "eager-orchid.json", "ses_wrong", "eager-orchid")
    _write_json(root / "tm_ouc" / "eager-orchid.json", "ses_fdbe", "eager-orchid")
    found = persist_snapshot({"slug": "eager-orchid", "session_id": "ses_fdbe"}, root)
    assert found == root / "tm_ouc" / "eager-orchid.json"


def test_snapshot_picks_newest_legal_source(tmp_path: Path):
    import os

    root = tmp_path / "sessions" / "opencode"
    older = root / "tm_ouc" / "eager-orchid.json"
    newer = root / "tm_andy_home" / "eager-orchid.json"
    _write_json(older, "ses_fdbe", "eager-orchid")
    _write_json(newer, "ses_fdbe", "eager-orchid")
    os.utime(older, (1, 1))
    os.utime(newer, (100, 100))
    found = persist_snapshot({"slug": "eager-orchid", "session_id": "ses_fdbe"}, root)
    assert found == newer


def test_ensure_local_imports_trigger_only(tmp_path: Path, monkeypatch):
    root = tmp_path / "sessions" / "opencode"
    snap = root / "tm_ouc" / "eager-orchid.json"
    _write_json(snap, "ses_fdbe", "eager-orchid")
    monkeypatch.setenv("OPENCODE_SESSIONS", str(root))
    imported: list[Path] = []

    def fake_by_id(sid: str):
        return None if sid not in imported_ids else object()

    imported_ids: set[str] = set()

    def fake_import(path: Path) -> None:
        imported.append(path)
        imported_ids.add("ses_fdbe")

    monkeypatch.setattr("dual_tmux.oc.by_id", fake_by_id)
    assert ensure_local({"session_id": "ses_fdbe", "slug": "eager-orchid"}, importer=fake_import)
    assert imported == [snap]
    assert ensure_local({"session_id": "ses_fdbe", "slug": "eager-orchid"}, importer=fake_import) is False


def test_ensure_local_missing_json(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENCODE_SESSIONS", str(tmp_path / "empty"))
    monkeypatch.setattr("dual_tmux.oc.by_id", lambda _sid: None)
    with pytest.raises(SystemExit, match="no persist JSON"):
        ensure_local({"session_id": "ses_missing", "slug": "eager-orchid"})
