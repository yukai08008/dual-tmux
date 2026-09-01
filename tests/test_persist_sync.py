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


def test_hotfix_identity_and_trees(tmp_path: Path, monkeypatch):
    from dual_tmux import hotfix
    from dual_tmux.config import AppConfig, write_config

    home = tmp_path / "dt"
    persist = tmp_path / "persist"
    sessions = tmp_path / "sessions"
    monkeypatch.setenv("DUAL_TMUX_HOME", str(home))
    monkeypatch.setenv("DT_PERSIST_CONFIG", str(persist))
    monkeypatch.setenv("DT_SESSIONS_HOME", str(sessions))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    persist.mkdir()
    (persist / "name").write_text("MacBookPro\n")
    monkeypatch.setattr(hotfix, "install_tick", lambda: hotfix.Step("tick-cron", True, "skip", False))
    monkeypatch.setattr(hotfix, "install_feishu_daemon", lambda: hotfix.Step("feishu-daemon", True, "skip", False))
    monkeypatch.setattr(hotfix, "install_persist_sync", lambda cfg: hotfix.Step("persist-cron", True, "skip", False))
    steps = hotfix.apply(ssh=False)
    ids = {s.id: s for s in steps}
    assert ids["identity"].ok
    assert (persist / "name").read_text().strip() == "tm_box"
    assert (persist / "user").read_text().strip() == "andy"
    assert (sessions / "opencode" / "tm_box").is_dir()
    assert (sessions / "tmux" / "tm_box").is_dir()
    assert hotfix.stamp_path().read_text().strip() == hotfix.HOTFIX_ID
    assert not hotfix.needed()


def test_persist_script_uses_tenant_not_login_home():
    from dual_tmux.hotfix import persist_script

    body = persist_script("opencode", "tom7r", "andy")
    assert "andy/sessions/opencode" in body
    assert "HOST:sessions/opencode" not in body
    assert "andy_messenger" not in body
    assert "tm_*" in body
    assert 'grep -Fqx "server = \\"$HOST\\""' in body
