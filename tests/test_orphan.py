import json
import subprocess

import pytest

from dual_tmux import cli, log, orphan
from dual_tmux.store import save, tunnels_dir


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))


def _tunnel(**extra) -> dict:
    data = {
        "name": "dt-x",
        "op": "op_x",
        "run": "run_x",
        "trigger": {"tool": "opencode"},
        "bullet": {"tool": "opencode", "session_id": "ses_b1"},
        "runtime": {
            "server": "box",
            "container": "c1",
            "directory": "/workspace",
            "cmd": "ssh box",
        },
    }
    data.update(extra)
    return data


def _fake_remote(monkeypatch, stdout="", returncode=0, error=None):
    calls = []

    def run(data, script, *, runner=None, **_kw):
        calls.append(script)
        if error is not None:
            raise error
        return subprocess.CompletedProcess([], returncode, stdout, "")

    monkeypatch.setattr("dual_tmux.orphan._remote_command", run)
    return calls


def _scan_lines(*rows):
    return "".join(f"PID={pid} AGE={age} ARGS={args}\n" for pid, age, args in rows)


# --- scan ----------------------------------------------------------------


def test_scan_keeps_newest_bound_session_and_flags_older_duplicates(monkeypatch):
    _fake_remote(
        monkeypatch,
        stdout=_scan_lines(
            (11, 864000, "opencode --auto -s ses_b1"),
            (12, 30, "opencode --auto -s ses_b1"),
            (13, 7200, "opencode"),
        ),
    )
    info = orphan.scan(_tunnel())
    assert info["status"] == "ok"
    assert info["legal"]["pid"] == 12  # newest bound-sid process survives
    assert sorted(p["pid"] for p in info["orphans"]) == [11, 13]


def test_scan_grace_window_holds_recent_candidates(monkeypatch):
    _fake_remote(
        monkeypatch,
        stdout=_scan_lines(
            (11, 300, "opencode --auto -s ses_b1"),
            (12, 30, "opencode --auto -s ses_b1"),
        ),
    )
    info = orphan.scan(_tunnel())
    assert info["legal"]["pid"] == 12
    assert info["orphans"] == []  # duplicate is only 300s old: inside grace


def test_scan_without_bound_session_protects_newest_overall(monkeypatch):
    _fake_remote(
        monkeypatch,
        stdout=_scan_lines(
            (21, 900, "opencode"),
            (22, 60, "opencode"),
        ),
    )
    info = orphan.scan(_tunnel())
    assert info["legal"]["pid"] == 22
    assert [p["pid"] for p in info["orphans"]] == [21]


def test_scan_skips_non_container_and_unreachable(monkeypatch):
    local = _tunnel()
    local["runtime"] = {"server": "", "container": "", "directory": "/tmp"}
    assert orphan.scan(local)["status"] == "not-applicable"
    _fake_remote(monkeypatch, returncode=255)
    assert orphan.scan(_tunnel())["status"] == "unavailable"
    _fake_remote(monkeypatch, error=OSError("ssh gone"))
    assert orphan.scan(_tunnel())["status"] == "unavailable"


def test_scan_ignores_the_exec_wrapper_itself(monkeypatch):
    _fake_remote(
        monkeypatch,
        stdout=_scan_lines(
            (24427, 0, "sh -lc tick=$(getconf CLK_TCK) ... [o]pencode ..."),
            (31, 5000, "opencode --auto -s ses_b1"),
        ),
    )
    info = orphan.scan(_tunnel())
    assert [p["pid"] for p in info["processes"]] == [31]
    assert info["legal"]["pid"] == 31 and info["orphans"] == []


# --- clean / sweep --------------------------------------------------------


def test_clean_terms_and_kills_with_events(monkeypatch):
    calls = _fake_remote(monkeypatch, stdout="REMAINING=0\n")
    orphans = [{"pid": 11, "age": 900, "args": "opencode"}]
    out = orphan.clean(_tunnel(), orphans)
    assert out["remaining"] == 0
    assert "kill -TERM" in calls[0] and "kill -KILL" in calls[0]
    row = log.read_events(limit=5, kind="orphan.clean")[-1]
    assert row["kind"] == "orphan.clean.ok"
    assert row["terminated"] == [11]


def test_clean_fail_reports_survivors(monkeypatch):
    _fake_remote(monkeypatch, stdout="REMAINING=1\n")
    orphans = [{"pid": 11, "age": 900, "args": "opencode"}]
    out = orphan.clean(_tunnel(), orphans)
    assert out["remaining"] == 1
    assert log.read_events(limit=5, kind="orphan.clean.fail")


def test_clean_noop_without_orphans(monkeypatch):
    calls = _fake_remote(monkeypatch)
    assert orphan.clean(_tunnel(), []) == {"terminated": [], "killed": [], "remaining": 0}
    assert calls == []


def test_sweep_kills_everything_and_emits(monkeypatch):
    calls = _fake_remote(
        monkeypatch,
        stdout=_scan_lines((11, 864000, "opencode --auto -s ses_b1")),
    )
    swept = orphan.sweep_run_point(_tunnel(), reason="rebuild")
    assert swept == [11]
    assert "kill -TERM" in calls[1]
    row = log.read_events(limit=5, kind="orphan.sweep")[-1]
    assert row["reason"] == "rebuild" and row["pids"] == [11]


def test_sweep_fail_closed_on_unreachable(monkeypatch):
    _fake_remote(monkeypatch, returncode=255)
    assert orphan.sweep_run_point(_tunnel(), reason="resume") is None


# --- patrol ---------------------------------------------------------------


def _patrol_env(monkeypatch, *, foreign=False, auto=False, dst=False):
    _fake_remote(
        monkeypatch,
        stdout=_scan_lines(
            (11, 864000, "opencode --auto -s ses_b1"),
            (12, 30, "opencode --auto -s ses_b1"),
        ),
    )
    data = _tunnel(auto_orphan_clean=auto)
    save(tunnels_dir() / "dt-x.json", data)
    monkeypatch.setattr(orphan, "foreign_held", lambda _d: foreign)
    if dst:
        from dual_tmux import oc as oc_mod

        monkeypatch.setattr(oc_mod, "is_dst", lambda _d: True)
    return data


def test_patrol_reports_without_cleaning_by_default(monkeypatch):
    data = _patrol_env(monkeypatch)
    out = orphan.patrol(data)
    assert out["clean"] is None
    row = log.read_events(limit=5, kind="orphan.found")[-1]
    assert row["pids"] == [11] and row["sev"] == "warn"
    assert not log.read_events(limit=5, kind="orphan.clean.ok")


def test_patrol_cleans_when_auto_enabled(monkeypatch):
    data = _patrol_env(monkeypatch, auto=True)
    out = orphan.patrol(data)
    assert out["clean"]["remaining"] == 0
    assert log.read_events(limit=5, kind="orphan.clean.ok")


def test_patrol_frozen_dst_is_scan_only(monkeypatch):
    data = _patrol_env(monkeypatch, auto=True, dst=True)
    out = orphan.patrol(data)
    assert out["frozen"] is True and out["clean"] is None
    assert log.read_events(limit=5, kind="orphan.found")
    assert not log.read_events(limit=5, kind="orphan.clean.ok")


def test_patrol_skips_foreign_occupancy(monkeypatch):
    data = _patrol_env(monkeypatch, foreign=True)
    assert orphan.patrol(data) is None
    assert not log.read_events(limit=5, kind="orphan.found")


def test_maybe_patrol_throttles_by_marker(monkeypatch):
    data = _patrol_env(monkeypatch)
    assert orphan.maybe_patrol(data, now=1000) is True
    assert orphan.maybe_patrol(data, now=1000 + 60) is False
    assert orphan.maybe_patrol(data, now=1000 + 3601) is True


# --- dt orphans command ----------------------------------------------------


def test_cmd_orphans_json_and_clean(monkeypatch, capsys):
    _patrol_env(monkeypatch)
    cli.cmd_orphans(type("Args", (), {"name": "dt-x", "json": True, "clean": False})())
    payload = json.loads(capsys.readouterr().out)
    assert payload["legal"]["pid"] == 12
    assert [p["pid"] for p in payload["orphans"]] == [11]
    cli.cmd_orphans(type("Args", (), {"name": "dt-x", "json": False, "clean": True})())
    assert log.read_events(limit=5, kind="orphan.clean.ok")


def test_cmd_orphans_skips_foreign(monkeypatch, capsys):
    _patrol_env(monkeypatch, foreign=True)
    cli.cmd_orphans(type("Args", (), {"name": "dt-x", "json": True, "clean": False})())
    assert "skipped" in capsys.readouterr().out


# --- registry / filters ----------------------------------------------------


def test_orphan_category_and_log_filter():
    assert "orphan" in log.CATEGORIES
    for kind in ("orphan.found", "orphan.clean.ok", "orphan.clean.fail", "orphan.sweep"):
        assert log.meta(kind)["cat"] == "orphan"
    assert log.meta("orphan.found")["sev"] == "warn"
    assert log.meta("orphan.clean.fail")["sev"] == "error"
    args = cli.build_parser().parse_args(["log", "--cat", "orphan"])
    assert args.cat == "orphan"
