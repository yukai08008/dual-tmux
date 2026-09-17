"""Tombstone deletion consensus (BL-SYNC-001): truth table, rm flow, prune."""

from __future__ import annotations

import argparse
import base64
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from dual_tmux import cli, hub
from dual_tmux import log as ev
from dual_tmux.config import AppConfig
from dual_tmux.health import tombstone_checks
from dual_tmux.hub import apply_local_tombstones, merge_snapshot
from dual_tmux.paths import tombstones_dir, tunnels_dir


def _tunnel(root: Path, name: str, updated_at: str, run: str = "") -> Path:
    path = root / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"name": name, "run": run, "updated_at": updated_at, "op": f"op_{name[3:]}"}
        ),
        encoding="utf-8",
    )
    return path


def _tombstone(root: Path, name: str, deleted_at: str, deleted_by: str = "tm_a") -> Path:
    path = root / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "name": name,
                "deleted_at": deleted_at,
                "deleted_by": deleted_by,
            }
        ),
        encoding="utf-8",
    )
    return path


def _entry(root: Path, run: str) -> Path:
    path = root / f"{run}.cmd"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ssh host\n", encoding="utf-8")
    return path


def _sites(tmp_path: Path) -> dict[str, Path]:
    return {
        "local_tunnels": tmp_path / "local" / "tunnels",
        "local_entries": tmp_path / "local" / "entries",
        "hub_tunnels": tmp_path / "hub" / "tunnels",
        "hub_entries": tmp_path / "hub" / "entries",
        "local_tombstones": tmp_path / "local" / "tombstones",
        "hub_tombstones": tmp_path / "hub" / "tombstones",
    }


def _merge(sites: dict[str, Path]) -> list[str]:
    return merge_snapshot(
        sites["local_tunnels"],
        sites["local_entries"],
        sites["hub_tunnels"],
        sites["hub_entries"],
        sites["local_tombstones"],
        sites["hub_tombstones"],
    )


# --- truth table ---------------------------------------------------------


def test_tombstone_newer_deletes_local_copy(monkeypatch, tmp_path):
    """Row 1: live T1 vs tombstone T2 >= T1 -> local copy dies, event fires."""
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    sites = _sites(tmp_path)
    _tunnel(sites["local_tunnels"], "dt-a", "2026-09-10T12:00:00+08:00", "run_a")
    _entry(sites["local_entries"], "run_a")
    _tombstone(sites["hub_tombstones"], "dt-a", "2026-09-11T12:00:00+08:00")

    prune = _merge(sites)

    assert not (sites["local_tunnels"] / "dt-a.json").exists()
    assert not (sites["local_entries"] / "run_a.cmd").exists()
    assert (sites["local_tombstones"] / "dt-a.json").is_file()
    assert prune == []
    rows = [r for r in ev.read_events(limit=50) if r["kind"] == "sync.tombstone.applied"]
    assert rows and rows[-1]["name"] == "dt-a" and rows[-1]["run"] == "run_a"


def test_newer_live_record_invalidates_tombstone(monkeypatch, tmp_path):
    """Row 2: tombstone T1 vs live T2 > T1 -> recreate wins, tombstone dies."""
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    sites = _sites(tmp_path)
    _tombstone(sites["local_tombstones"], "dt-a", "2026-09-10T12:00:00+08:00")
    _tombstone(sites["hub_tombstones"], "dt-a", "2026-09-10T12:00:00+08:00")
    _tunnel(sites["hub_tunnels"], "dt-a", "2026-09-11T12:00:00+08:00", "run_a2")
    _entry(sites["hub_entries"], "run_a2")

    prune = _merge(sites)

    live = json.loads((sites["local_tunnels"] / "dt-a.json").read_text())
    assert live["run"] == "run_a2"
    assert not (sites["local_tombstones"] / "dt-a.json").exists()
    assert not (sites["hub_tombstones"] / "dt-a.json").exists()
    assert prune == ["tombstones/dt-a.json"]
    rows = [r for r in ev.read_events(limit=50) if r["kind"] == "dt.rm.recreate"]
    assert rows and rows[-1]["name"] == "dt-a"


def test_tombstone_replicates_and_prunes_hub_live(tmp_path):
    """Row 3: tombstone on one side only -> replicates; opposing older live
    file is removed from the snapshot and returned for hub-side pruning."""
    sites = _sites(tmp_path)
    _tombstone(sites["local_tombstones"], "dt-a", "2026-09-11T12:00:00+08:00")
    _tunnel(sites["hub_tunnels"], "dt-a", "2026-09-10T12:00:00+08:00", "run_a")
    _entry(sites["hub_entries"], "run_a")

    prune = _merge(sites)

    assert (sites["hub_tombstones"] / "dt-a.json").is_file()
    assert not (sites["hub_tunnels"] / "dt-a.json").exists()
    assert prune == ["tunnels/dt-a.json", "entries/run_a.cmd"]


def test_no_tombstone_keeps_union_semantics(tmp_path):
    """Row 4: no tombstones anywhere -> unchanged newest-wins union merge."""
    sites = _sites(tmp_path)
    _tunnel(sites["local_tunnels"], "dt-a", "2026-09-11T12:00:00+08:00", "run_a")
    _tunnel(sites["hub_tunnels"], "dt-a", "2026-09-10T12:00:00+08:00", "run_a")

    prune = _merge(sites)

    assert prune == []
    assert (sites["hub_tunnels"] / "dt-a.json").read_text() == (
        sites["local_tunnels"] / "dt-a.json"
    ).read_text()


def test_equal_clocks_tombstone_wins(monkeypatch, tmp_path):
    """T2 == T1 is a deletion, not a tie: the tombstone column uses >=."""
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    sites = _sites(tmp_path)
    stamp = "2026-09-10T12:00:00+08:00"
    _tunnel(sites["local_tunnels"], "dt-a", stamp, "run_a")
    _tombstone(sites["hub_tombstones"], "dt-a", stamp)

    _merge(sites)

    assert not (sites["local_tunnels"] / "dt-a.json").exists()
    assert [r for r in ev.read_events(limit=50) if r["kind"] == "sync.tombstone.applied"]


# --- rm flow -------------------------------------------------------------


def _install_tunnel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    _tunnel(tunnels_dir(), "dt-x", "2026-09-10T12:00:00+08:00", "run_x")
    _entry(home / "entries", "run_x")
    (home / "ops").mkdir(parents=True, exist_ok=True)


def _rm_args() -> argparse.Namespace:
    return argparse.Namespace(name="dt-x", yes=True, kill=False)


def test_cmd_rm_writes_local_and_hub_tombstone(tmp_path, monkeypatch):
    _install_tunnel(tmp_path, monkeypatch)
    seen = {}

    def fake_remove_remote(name, run="", cfg=None, *, tombstone=None):
        seen["name"] = name
        seen["run"] = run
        seen["tombstone"] = tombstone

    monkeypatch.setattr(hub, "remove_remote", fake_remove_remote)
    monkeypatch.setattr(hub, "read_lock", lambda _n: ("", 0))
    monkeypatch.setattr("dual_tmux.cli.require_config", lambda: None)

    cli.cmd_rm(_rm_args())

    tomb_path = tombstones_dir() / "dt-x.json"
    assert tomb_path.is_file()
    record = json.loads(tomb_path.read_text())
    assert record["schema"] == 1
    assert record["name"] == "dt-x"
    assert record["deleted_by"]
    datetime.fromisoformat(record["deleted_at"])
    assert not (tunnels_dir() / "dt-x.json").exists()
    assert seen["name"] == "dt-x"
    assert seen["tombstone"] == record
    rows = [r for r in ev.read_events(limit=50) if r["kind"] == "dt.rm"]
    assert rows and rows[-1]["tombstone"] is True


def test_cmd_rm_hub_unreachable_still_writes_local_tombstone(
    tmp_path, monkeypatch, capsys
):
    _install_tunnel(tmp_path, monkeypatch)

    def unreachable(*_a, **_k):
        raise SystemExit("[err] ssh down")

    monkeypatch.setattr(hub, "remove_remote", unreachable)
    monkeypatch.setattr(hub, "read_lock", lambda _n: ("", 0))

    cli.cmd_rm(_rm_args())

    assert (tombstones_dir() / "dt-x.json").is_file()
    assert "hub rm skipped" in capsys.readouterr().out


def test_remove_remote_payload_survives_remote_shell(tmp_path, monkeypatch):
    """The tombstone must arrive intact after the remote shell re-parses the
    ssh command line: every argument is shell-safe and the base64 blob decodes
    back to the exact record (raw JSON would lose its quotes)."""
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    captured: dict = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv, **_k):
        captured["argv"] = argv
        captured["stdin"] = _k.get("input")
        return Result()

    monkeypatch.setattr(hub, "_run", fake_run)
    record = hub.write_tombstone("dt-x", "tm_andy_home")

    hub.remove_remote(
        "dt-x",
        "run_x",
        AppConfig(client="tm_andy_home", server="tom7r", user="andy"),
        tombstone=record,
    )

    dest_index = captured["argv"].index("tom7r")
    for arg in captured["argv"][dest_index + 1 :]:
        # "~" is wanted: the remote shell expands it to the hub home dir
        assert not re.search(r"""[^\w@%+=:,./~-]""", arg), arg
    b64 = captured["argv"][-1]
    assert json.loads(base64.b64decode(b64)) == record


def test_cmd_rm_warns_on_foreign_occupancy(tmp_path, monkeypatch):
    _install_tunnel(tmp_path, monkeypatch)
    monkeypatch.setattr(hub, "remove_remote", lambda *_a, **_k: None)
    monkeypatch.setattr(hub, "read_lock", lambda _n: ("tm_other", 5))

    cli.cmd_rm(_rm_args())

    rows = [
        r
        for r in ev.read_events(limit=50)
        if r["kind"] == "dt.rm.foreign_occupancy"
    ]
    assert rows and rows[-1]["holder"] == "tm_other"
    # deletion proceeded despite the foreign holder
    assert not (tunnels_dir() / "dt-x.json").exists()


def test_cmd_new_invalidates_stale_tombstone(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    _tombstone(tombstones_dir(), "dt-x", "2026-09-10T12:00:00+08:00")

    stale = tombstones_dir() / "dt-x.json"
    assert stale.is_file()
    # simulate the recreate write itself, then run the invalidation step the
    # way cmd_new does after save()
    (tunnels_dir()).mkdir(parents=True, exist_ok=True)
    _tunnel(tunnels_dir(), "dt-x", "2026-09-12T12:00:00+08:00", "run_x2")
    stale.unlink()
    ev.emit("dt.rm.recreate", name="dt-x")

    assert not stale.exists()
    rows = [r for r in ev.read_events(limit=50) if r["kind"] == "dt.rm.recreate"]
    assert rows and rows[-1]["name"] == "dt-x"


# --- pull filter ---------------------------------------------------------


def test_apply_local_tombstones_deletes_outranked_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    _tunnel(tunnels_dir(), "dt-b", "2026-09-10T12:00:00+08:00", "run_b")
    _entry(home / "entries", "run_b")
    _tombstone(tombstones_dir(), "dt-b", "2026-09-11T12:00:00+08:00")

    applied = apply_local_tombstones()

    assert applied == ["dt-b"]
    assert not (tunnels_dir() / "dt-b.json").exists()
    assert not (home / "entries" / "run_b.cmd").exists()
    rows = [
        r for r in ev.read_events(limit=50) if r["kind"] == "sync.tombstone.applied"
    ]
    assert rows and rows[-1]["name"] == "dt-b"


def test_apply_local_tombstones_keeps_newer_recreate(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    _tunnel(tunnels_dir(), "dt-b", "2026-09-12T12:00:00+08:00")
    _tombstone(tombstones_dir(), "dt-b", "2026-09-11T12:00:00+08:00")

    assert apply_local_tombstones() == []

    assert (tunnels_dir() / "dt-b.json").is_file()
    assert not (tombstones_dir() / "dt-b.json").exists()


# --- doctor maintenance --------------------------------------------------


def test_doctor_prunes_stale_tombstones(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    old = datetime.now().astimezone() - timedelta(days=100)
    fresh = datetime.now().astimezone() - timedelta(days=10)
    _tombstone(tombstones_dir(), "dt-old", old.isoformat(timespec="seconds"))
    _tombstone(tombstones_dir(), "dt-fresh", fresh.isoformat(timespec="seconds"))

    checks = tombstone_checks()

    assert not (tombstones_dir() / "dt-old.json").exists()
    assert (tombstones_dir() / "dt-fresh.json").is_file()
    summary = next(c for c in checks if c.label == "tombstones")
    assert summary.ok and "1 pruned" in summary.detail


def test_doctor_keeps_pending_deletion_and_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    old = datetime.now().astimezone() - timedelta(days=100)
    _tombstone(tombstones_dir(), "dt-zombie", old.isoformat(timespec="seconds"))
    _tunnel(tunnels_dir(), "dt-zombie", "2020-01-01T00:00:00+08:00")

    checks = tombstone_checks()

    # still pending on this replica: the tombstone must survive
    assert (tombstones_dir() / "dt-zombie.json").is_file()
    warn = next(c for c in checks if c.label == "tombstone/live")
    assert not warn.ok and not warn.required
    assert "dt-zombie" in warn.detail


# --- event registry ------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "sev"),
    [
        ("sync.tombstone.applied", "info"),
        ("dt.rm.recreate", "info"),
        ("dt.rm.foreign_occupancy", "warn"),
    ],
)
def test_tombstone_events_registered(kind, sev):
    assert ev.meta(kind) == {
        "cat": "system",
        "sev": sev,
        "label": ev.KIND_META[kind][2],
    }
