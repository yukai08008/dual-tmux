import json
import os
import time
from pathlib import Path

import pytest

from dual_tmux import oc


def _info(sid="ses_abc123", slug="misty-rocket", tool="opencode"):
    return {"session_id": sid, "slug": slug, "tool": tool}


def _runner_ok(payload):
    def run(argv, **kwargs):
        kwargs["stdout"].write(json.dumps(payload))

        class R:
            returncode = 0
            stderr = ""

        return R()

    return run


@pytest.fixture
def local_session(monkeypatch):
    monkeypatch.setattr(oc, "by_id", lambda sid: object())
    monkeypatch.setattr(oc, "session_updated_ms", lambda sid: 1_000_000)


def test_export_writes_snapshot(tmp_path: Path, local_session):
    dest = oc.export_snapshot(
        _info(),
        "tm_a",
        root=tmp_path,
        runner=_runner_ok({"info": {"id": "ses_abc123"}}),
    )
    assert dest == tmp_path / "tm_a" / "misty-rocket.json"
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["info"]["id"] == "ses_abc123"


def test_export_skips_when_fresh(tmp_path: Path, monkeypatch, local_session):
    dest = tmp_path / "tm_a" / "misty-rocket.json"
    dest.parent.mkdir(parents=True)
    dest.write_text("{}", encoding="utf-8")
    os.utime(dest, (time.time() + 3600, time.time() + 3600))

    def runner(*a, **k):
        raise AssertionError("export must not run when fresh")

    assert oc.export_snapshot(_info(), "tm_a", root=tmp_path, runner=runner) is None


def test_export_none_when_session_not_local(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(oc, "by_id", lambda sid: None)
    assert (
        oc.export_snapshot(_info(), "tm_a", root=tmp_path, runner=_runner_ok({}))
        is None
    )
    assert not (tmp_path / "tm_a").exists()


def test_export_none_without_sid_or_wrong_tool(tmp_path: Path, local_session):
    assert oc.export_snapshot({}, "tm_a", root=tmp_path) is None
    assert oc.export_snapshot(_info(tool="codex"), "tm_a", root=tmp_path) is None
    assert oc.export_snapshot(_info(), "", root=tmp_path) is None


def test_export_failure_cleans_tmp(tmp_path: Path, local_session):
    class R:
        returncode = 1
        stderr = "boom"

    def run(argv, **kwargs):
        return R()

    with pytest.raises(SystemExit):
        oc.export_snapshot(_info(), "tm_a", root=tmp_path, runner=run)
    assert not list((tmp_path / "tm_a").glob("*"))


def test_export_rejects_id_mismatch(tmp_path: Path, local_session):
    with pytest.raises(SystemExit):
        oc.export_snapshot(
            _info(),
            "tm_a",
            root=tmp_path,
            runner=_runner_ok({"info": {"id": "ses_other"}}),
        )
    assert not (tmp_path / "tm_a" / "misty-rocket.json").exists()


def test_export_falls_back_to_sid_filename(tmp_path: Path, local_session):
    dest = oc.export_snapshot(
        _info(slug=""),
        "tm_a",
        root=tmp_path,
        runner=_runner_ok({"info": {"id": "ses_abc123"}}),
    )
    assert dest.name == "ses_abc123.json"


def test_persist_tenant_prefers_name_file(monkeypatch, tmp_path: Path):
    name = tmp_path / ".config" / "session-persist" / "name"
    name.parent.mkdir(parents=True)
    name.write_text("tm_andy_ouc\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert oc.persist_tenant("tm_ouc") == "tm_andy_ouc"
    name.unlink()
    assert oc.persist_tenant("tm_ouc") == "tm_ouc"


def test_oc_bin_fallback(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        Path, "is_file", lambda self: str(self).endswith(".opencode/bin/opencode")
    )
    monkeypatch.setattr(os, "access", lambda p, m: True)
    assert oc.oc_bin().endswith(".opencode/bin/opencode")
