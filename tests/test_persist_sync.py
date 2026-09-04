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


def _write_json(
    path: Path,
    session_id: str,
    slug: str,
    *,
    updated: int = 0,
    messages: tuple[str, ...] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "info": {
                    "id": session_id,
                    "slug": slug,
                    "title": slug,
                    "time": {"updated": updated},
                },
                "messages": [{"info": {"id": mid}} for mid in messages],
            }
        ),
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


def test_snapshot_uses_payload_revision_not_file_mtime(tmp_path: Path):
    import os

    root = tmp_path / "sessions" / "opencode"
    newest = root / "tm_ouc" / "eager-orchid.json"
    stale = root / "tm_home" / "eager-orchid.json"
    _write_json(newest, "ses_fdbe", "eager-orchid", updated=200, messages=("msg_2",))
    _write_json(stale, "ses_fdbe", "eager-orchid", updated=100, messages=("msg_1",))
    os.utime(newest, (1, 1))
    os.utime(stale, (999, 999))
    assert persist_snapshot({"slug": "eager-orchid", "session_id": "ses_fdbe"}, root) == newest


def test_snapshot_rejects_divergent_same_revision(tmp_path: Path):
    root = tmp_path / "sessions" / "opencode"
    _write_json(
        root / "tm_ouc" / "eager-orchid.json",
        "ses_fdbe",
        "eager-orchid",
        updated=200,
        messages=("msg_a",),
    )
    _write_json(
        root / "tm_home" / "eager-orchid.json",
        "ses_fdbe",
        "eager-orchid",
        updated=200,
        messages=("msg_b",),
    )
    with pytest.raises(SystemExit, match="snapshot_conflict"):
        persist_snapshot({"slug": "eager-orchid", "session_id": "ses_fdbe"}, root)


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


def test_ensure_local_replaces_stale_same_id_after_backup(tmp_path: Path, monkeypatch):
    root = tmp_path / "sessions" / "opencode"
    snap = root / "tm_ouc" / "eager-orchid.json"
    _write_json(
        snap,
        "ses_fdbe",
        "eager-orchid",
        updated=200,
        messages=("msg_old", "msg_new"),
    )
    monkeypatch.setenv("OPENCODE_SESSIONS", str(root))
    monkeypatch.setattr("dual_tmux.oc.by_id", lambda _sid: object())
    monkeypatch.setattr("dual_tmux.oc.session_updated_ms", lambda _sid: 100)
    monkeypatch.setattr("dual_tmux.oc.local_tail_message_id", lambda _sid: "msg_old")
    imported: list[Path] = []
    backups: list[str] = []
    monkeypatch.setattr(
        "dual_tmux.oc.local_has_message", lambda _sid, mid: mid == "msg_new"
    )

    assert ensure_local(
        {"session_id": "ses_fdbe", "slug": "eager-orchid"},
        importer=imported.append,
        backupper=lambda sid: backups.append(sid) or tmp_path / "backup.json",
    )
    assert imported == [snap]
    assert backups == ["ses_fdbe"]


def test_ensure_local_does_not_downgrade_newer_local(tmp_path: Path, monkeypatch):
    root = tmp_path / "sessions" / "opencode"
    _write_json(
        root / "tm_ouc" / "eager-orchid.json",
        "ses_fdbe",
        "eager-orchid",
        updated=100,
        messages=("msg_old",),
    )
    monkeypatch.setenv("OPENCODE_SESSIONS", str(root))
    monkeypatch.setattr("dual_tmux.oc.by_id", lambda _sid: object())
    monkeypatch.setattr("dual_tmux.oc.session_updated_ms", lambda _sid: 200)
    monkeypatch.setattr("dual_tmux.oc.local_tail_message_id", lambda _sid: "msg_new")
    monkeypatch.setattr("dual_tmux.oc.local_has_message", lambda _sid, _mid: True)

    assert ensure_local(
        {"session_id": "ses_fdbe", "slug": "eager-orchid"},
        importer=lambda _path: pytest.fail("must not import an older snapshot"),
    ) is False


def test_ensure_local_rejects_non_ancestral_newer_snapshot(tmp_path: Path, monkeypatch):
    root = tmp_path / "sessions" / "opencode"
    _write_json(
        root / "tm_ouc" / "eager-orchid.json",
        "ses_fdbe",
        "eager-orchid",
        updated=200,
        messages=("msg_other",),
    )
    monkeypatch.setenv("OPENCODE_SESSIONS", str(root))
    monkeypatch.setattr("dual_tmux.oc.by_id", lambda _sid: object())
    monkeypatch.setattr("dual_tmux.oc.session_updated_ms", lambda _sid: 100)
    monkeypatch.setattr("dual_tmux.oc.local_tail_message_id", lambda _sid: "msg_local")

    with pytest.raises(SystemExit, match="snapshot_conflict"):
        ensure_local({"session_id": "ses_fdbe", "slug": "eager-orchid"})


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
    assert 'WAIT="${2:-}"' in body
    assert 'exit "$failed"' in body
    assert "2>/dev/null || true" not in next(
        line for line in body.splitlines() if line.startswith('names="$(ssh')
    )
