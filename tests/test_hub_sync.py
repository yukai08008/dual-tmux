import base64
import json
import os
import shlex
from pathlib import Path

from dual_tmux import hub
from dual_tmux.config import AppConfig
from dual_tmux.hub import merge_snapshot


def test_rsync_can_disable_cross_host_uid_gid_preservation(monkeypatch):
    seen = []

    class Result:
        returncode = 0
        stderr = stdout = ""

    monkeypatch.setattr(hub, "_run", lambda argv: seen.append(argv) or Result())
    hub._rsync(
        "/local/route.json",
        "tom7r:/remote/route.json",
        AppConfig(client="tm_a", server="tom7r", user="a"),
        preserve_ownership=False,
    )
    assert "--no-owner" in seen[0]
    assert "--no-group" in seen[0]


def _tunnel(root: Path, name: str, updated_at: str, run: str, marker: str) -> Path:
    path = root / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"name": name, "run": run, "updated_at": updated_at, "marker": marker}),
        encoding="utf-8",
    )
    return path


def _entry(root: Path, run: str, text: str, mtime: int) -> Path:
    path = root / f"{run}.cmd"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_merge_snapshot_discovers_remote_and_preserves_newer_local(tmp_path: Path):
    local_tunnels = tmp_path / "local" / "tunnels"
    local_entries = tmp_path / "local" / "entries"
    hub_tunnels = tmp_path / "hub" / "tunnels"
    hub_entries = tmp_path / "hub" / "entries"

    _tunnel(hub_tunnels, "dt-remote", "2026-08-30T12:00:00+08:00", "run_remote", "hub")
    _entry(hub_entries, "run_remote", "ssh remote\n", 20)
    local_path = _tunnel(
        local_tunnels, "dt-local", "2026-08-31T12:00:00+08:00", "run_local", "local"
    )
    hub_path = _tunnel(hub_tunnels, "dt-local", "2026-08-29T12:00:00+08:00", "run_local", "stale")
    os.utime(local_path, (10, 10))
    os.utime(hub_path, (30, 30))
    old_hub_mtime = hub_path.stat().st_mtime
    _entry(local_entries, "run_local", "ssh local\n", 30)
    _entry(hub_entries, "run_local", "ssh stale\n", 10)

    merge_snapshot(local_tunnels, local_entries, hub_tunnels, hub_entries)

    assert json.loads((local_tunnels / "dt-remote.json").read_text())["marker"] == "hub"
    assert json.loads((hub_tunnels / "dt-local.json").read_text())["marker"] == "local"
    assert hub_path.stat().st_mtime > old_hub_mtime
    assert (local_entries / "run_remote.cmd").read_text() == "ssh remote\n"
    assert (hub_entries / "run_local.cmd").read_text() == "ssh local\n"


def test_merge_snapshot_prefers_newer_remote_binding(tmp_path: Path):
    local_tunnels = tmp_path / "local" / "tunnels"
    local_entries = tmp_path / "local" / "entries"
    hub_tunnels = tmp_path / "hub" / "tunnels"
    hub_entries = tmp_path / "hub" / "entries"
    _tunnel(local_tunnels, "dt-shared", "2026-08-30T12:00:00+08:00", "run_shared", "local")
    _tunnel(hub_tunnels, "dt-shared", "2026-08-31T12:00:00+08:00", "run_shared", "hub")
    _entry(local_entries, "run_shared", "ssh old\n", 10)
    _entry(hub_entries, "run_shared", "ssh new\n", 20)

    merge_snapshot(local_tunnels, local_entries, hub_tunnels, hub_entries)

    assert json.loads((local_tunnels / "dt-shared.json").read_text())["marker"] == "hub"
    assert (local_entries / "run_shared.cmd").read_text() == "ssh new\n"


def test_merge_snapshot_handles_missing_entry_and_equal_time_deterministically(tmp_path: Path):
    local_tunnels = tmp_path / "local" / "tunnels"
    local_entries = tmp_path / "local" / "entries"
    hub_tunnels = tmp_path / "hub" / "tunnels"
    hub_entries = tmp_path / "hub" / "entries"
    stamp = "2026-08-31T12:00:00+08:00"
    _tunnel(local_tunnels, "dt-tie", stamp, "run_missing", "alpha")
    _tunnel(hub_tunnels, "dt-tie", stamp, "run_missing", "beta")

    merge_snapshot(local_tunnels, local_entries, hub_tunnels, hub_entries)

    assert (local_tunnels / "dt-tie.json").read_bytes() == (hub_tunnels / "dt-tie.json").read_bytes()
    assert not (local_entries / "run_missing.cmd").exists()
    assert not (hub_entries / "run_missing.cmd").exists()


def test_read_ownership_synthesizes_v1_without_sidecar(monkeypatch):
    class Result:
        returncode = 0
        stderr = ""
        stdout = "V1 " + base64.b64encode(b"tm_old@1000@7\n").decode() + "\nV2 \n"

    cfg = AppConfig(client="tm_new", server="tom7r", user="andy")
    monkeypatch.setattr(hub, "_run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr(hub.time, "time", lambda: 1100)
    value = hub.read_ownership("dt-a", cfg)
    assert value["state"] == "foreign"
    assert value["holder"] == "tm_old"
    assert value["generation"] == 7
    assert value["source"] == "v1"
    assert value["conflict"] is False


def test_stale_sidecar_never_overrides_v1(monkeypatch):
    sidecar = {"holder": "tm_wrong", "generation": 2, "instance_id": "bad", "evidence": {"unsafe": True}}

    class Result:
        returncode = 0
        stderr = ""
        stdout = "\n".join([
            "V1 " + base64.b64encode(b"tm_owner@1000@9\n").decode(),
            "V2 " + base64.b64encode(json.dumps(sidecar).encode()).decode(),
        ])

    cfg = AppConfig(client="tm_owner", server="tom7r", user="andy")
    monkeypatch.setattr(hub, "_run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr(hub.time, "time", lambda: 1100)
    value = hub.read_ownership("dt-a", cfg)
    assert value["state"] == "owned"
    assert value["generation"] == 9
    assert value["instance_id"] == ""
    assert value["evidence"] == {}
    assert value["source"] == "v1"
    assert value["conflict"] is True


def test_handoff_remote_quotes_values_before_ssh_shell(monkeypatch):
    seen = []

    class Result:
        returncode = 0
        stderr = ""
        stdout = '{"ok":true,"generation":7}\n'

    monkeypatch.setattr(
        hub, "_run", lambda argv, **_kwargs: seen.append(argv) or Result()
    )
    monkeypatch.setattr(hub, "instance_id", lambda: "host; false")
    cfg = AppConfig(client="tm_new", server="tom7r", user="andy")

    value = hub._handoff_remote(
        "dt-a; false",
        "cancel",
        request_id="req; false",
        generation=7,
        cfg=cfg,
    )

    remote = shlex.split(seen[0][-1])
    assert remote[:4] == ["bash", "-s", "--", "andy/dual-tmux"]
    assert remote[4:9] == [
        "dt-a; false",
        "cancel",
        "req; false",
        "tm_new",
        "host; false",
    ]
    assert value["ok"] is True
