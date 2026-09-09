import base64
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest

from dual_tmux import hub
from dual_tmux.config import AppConfig
from dual_tmux.hub import merge_snapshot


def _local_remote_runner(argv, *, input=None, **_kwargs):
    """Execute an SSH payload locally against an isolated fake Hub root."""
    if len(argv) and isinstance(argv[-1], str) and argv[-1].startswith("bash "):
        command = shlex.split(argv[-1])
    else:
        command = argv[argv.index("bash") :]
    return subprocess.run(
        command,
        input=input,
        capture_output=True,
        text=True,
        check=False,
    )


def _install_test_flock(monkeypatch, tmp_path):
    """macOS lacks flock(1); sequential script tests only need a no-op shim."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "flock"
    shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")


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


def test_hub_lock_has_bounded_rpc_timeout(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(hub, "_run", run)
    with pytest.raises(SystemExit, match="hub lock timed out after 8s"):
        hub._lock_remote(
            "claim",
            "dt-a",
            cfg=AppConfig(client="tm_a", server="tom7r", user="andy"),
        )
    assert seen == [8]


def _tunnel(root: Path, name: str, updated_at: str, run: str, marker: str) -> Path:
    path = root / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"name": name, "run": run, "updated_at": updated_at, "marker": marker}
        ),
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
    hub_path = _tunnel(
        hub_tunnels, "dt-local", "2026-08-29T12:00:00+08:00", "run_local", "stale"
    )
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
    _tunnel(
        local_tunnels, "dt-shared", "2026-08-30T12:00:00+08:00", "run_shared", "local"
    )
    _tunnel(hub_tunnels, "dt-shared", "2026-08-31T12:00:00+08:00", "run_shared", "hub")
    _entry(local_entries, "run_shared", "ssh old\n", 10)
    _entry(hub_entries, "run_shared", "ssh new\n", 20)

    merge_snapshot(local_tunnels, local_entries, hub_tunnels, hub_entries)

    assert json.loads((local_tunnels / "dt-shared.json").read_text())["marker"] == "hub"
    assert (local_entries / "run_shared.cmd").read_text() == "ssh new\n"


def test_merge_snapshot_handles_missing_entry_and_equal_time_deterministically(
    tmp_path: Path,
):
    local_tunnels = tmp_path / "local" / "tunnels"
    local_entries = tmp_path / "local" / "entries"
    hub_tunnels = tmp_path / "hub" / "tunnels"
    hub_entries = tmp_path / "hub" / "entries"
    stamp = "2026-08-31T12:00:00+08:00"
    _tunnel(local_tunnels, "dt-tie", stamp, "run_missing", "alpha")
    _tunnel(hub_tunnels, "dt-tie", stamp, "run_missing", "beta")

    merge_snapshot(local_tunnels, local_entries, hub_tunnels, hub_entries)

    assert (local_tunnels / "dt-tie.json").read_bytes() == (
        hub_tunnels / "dt-tie.json"
    ).read_bytes()
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
    assert value["lease_ttl"] == hub.LOCK_TTL


def test_v2_sidecar_uses_short_lease_while_legacy_keeps_compatibility(monkeypatch):
    sidecar = {
        "lease_protocol": 2,
        "lease_ttl": hub.OWNERSHIP_LEASE_TTL,
        "holder": "tm_old",
        "instance_id": "old-instance",
        "generation": 7,
    }

    class Result:
        returncode = 0
        stderr = ""
        stdout = "\n".join(
            [
                "V1 " + base64.b64encode(b"tm_old@1000@7\n").decode(),
                "V2 " + base64.b64encode(json.dumps(sidecar).encode()).decode(),
            ]
        )

    cfg = AppConfig(client="tm_new", server="tom7r", user="andy")
    monkeypatch.setattr(hub, "_run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr(hub.time, "time", lambda: 1000 + hub.OWNERSHIP_LEASE_TTL + 1)

    value = hub.read_ownership("dt-a", cfg)

    assert value["state"] == "expired"
    assert value["lease_protocol"] == 2
    assert value["lease_ttl"] == hub.OWNERSHIP_LEASE_TTL


def test_legacy_owner_can_renew_once_and_upgrade_to_short_lease(monkeypatch, tmp_path):
    cfg = AppConfig(client="tm_old", server="fake", user="tenant")
    root = tmp_path / "hub"
    _install_test_flock(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "_run", _local_remote_runner)
    monkeypatch.setattr(hub, "remote_root", lambda _cfg=None: str(root))
    monkeypatch.setattr(hub, "instance_id", lambda: "legacy-instance")
    (root / "locks").mkdir(parents=True)
    (root / "locks" / "dt-a").write_text(
        f"tm_old@{int(time.time())}@7\n", encoding="utf-8"
    )

    renewed = hub.renew_ownership("dt-a", 7, cfg=cfg)

    assert renewed == {"holder": "tm_old", "generation": 7}
    sidecar = json.loads((root / "ownership" / "dt-a.json").read_text())
    assert sidecar["lease_protocol"] == 2
    assert sidecar["instance_id"] == "legacy-instance"


def test_renew_requires_same_client_instance_and_generation(monkeypatch, tmp_path):
    cfg = AppConfig(client="tm_a", server="fake", user="tenant")
    root = tmp_path / "hub"
    _install_test_flock(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "_run", _local_remote_runner)
    monkeypatch.setattr(hub, "remote_root", lambda _cfg=None: str(root))
    monkeypatch.setattr(hub, "instance_id", lambda: "instance-a")
    kind, _, _, generation = hub._lock_remote(
        "claim", "dt-a", cfg=cfg, ttl=hub.OWNERSHIP_LEASE_TTL
    )
    assert kind == "OK"

    renewed = hub.renew_ownership("dt-a", generation, cfg=cfg)
    before = (root / "ownership" / "dt-a.json").read_bytes()
    assert renewed == {"holder": "tm_a", "generation": generation}

    monkeypatch.setattr(hub, "instance_id", lambda: "instance-b")
    with pytest.raises(SystemExit, match="renewal fenced"):
        hub.renew_ownership("dt-a", generation, cfg=cfg)
    assert (root / "ownership" / "dt-a.json").read_bytes() == before

    monkeypatch.setattr(hub, "instance_id", lambda: "instance-a")
    with pytest.raises(SystemExit, match="renewal fenced"):
        hub.renew_ownership("dt-a", generation + 1, cfg=cfg)
    assert (root / "ownership" / "dt-a.json").read_bytes() == before


def test_exact_v2_owner_can_recover_expired_lease_before_takeover(
    monkeypatch, tmp_path
):
    cfg = AppConfig(client="tm_a", server="fake", user="tenant")
    root = tmp_path / "hub"
    _install_test_flock(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "_run", _local_remote_runner)
    monkeypatch.setattr(hub, "remote_root", lambda _cfg=None: str(root))
    monkeypatch.setattr(hub, "instance_id", lambda: "instance-a")
    monkeypatch.setattr(hub, "existing_instance_id", lambda: "instance-a")
    _, _, _, generation = hub._lock_remote(
        "claim", "dt-a", cfg=cfg, ttl=hub.OWNERSHIP_LEASE_TTL
    )
    expired = int(time.time()) - hub.OWNERSHIP_LEASE_TTL - 20
    (root / "locks" / "dt-a").write_text(
        f"tm_a@{expired}@{generation}\n", encoding="utf-8"
    )
    side = root / "ownership" / "dt-a.json"
    payload = json.loads(side.read_text(encoding="utf-8"))
    payload.update(renewed_at=expired, expires_at=expired + hub.OWNERSHIP_LEASE_TTL)
    side.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert hub.renew_ownership("dt-a", generation, cfg=cfg) == {
        "holder": "tm_a",
        "generation": generation,
    }
    assert hub.read_ownership("dt-a", cfg)["state"] == "owned"


def test_expired_v2_owner_cannot_renew_after_takeover_reservation(
    monkeypatch, tmp_path
):
    old_cfg = AppConfig(client="tm_old", server="fake", user="tenant")
    new_cfg = AppConfig(client="tm_new", server="fake", user="tenant")
    root = tmp_path / "hub"
    _install_test_flock(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "_run", _local_remote_runner)
    monkeypatch.setattr(hub, "remote_root", lambda _cfg=None: str(root))
    monkeypatch.setattr(hub, "instance_id", lambda: "old-instance")
    _, _, _, generation = hub._lock_remote(
        "claim", "dt-a", cfg=old_cfg, ttl=hub.OWNERSHIP_LEASE_TTL
    )
    expired = 1
    (root / "locks" / "dt-a").write_text(
        f"tm_old@{expired}@{generation}\n", encoding="utf-8"
    )
    side = root / "ownership" / "dt-a.json"
    payload = json.loads(side.read_text(encoding="utf-8"))
    payload.update(renewed_at=expired, expires_at=expired + hub.OWNERSHIP_LEASE_TTL)
    side.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    monkeypatch.setattr(hub, "load_config", lambda: new_cfg)
    monkeypatch.setattr(hub, "instance_id", lambda: "new-instance")
    hub.reserve_fault_takeover("dt-a", generation)

    monkeypatch.setattr(hub, "instance_id", lambda: "old-instance")
    with pytest.raises(SystemExit, match="renewal fenced"):
        hub.renew_ownership("dt-a", generation, cfg=old_cfg)


def test_renew_retries_same_generation_flock_contention(monkeypatch):
    cfg = AppConfig(client="tm_a", server="fake", user="tenant")
    replies = iter(
        [
            ("HELD", "tm_a", 0, 7),
            ("HELD", "tm_a", 0, 7),
            ("OK", "tm_a", 0, 7),
        ]
    )
    monkeypatch.setattr(hub, "_lock_remote", lambda *_a, **_kw: next(replies))
    monkeypatch.setattr(hub.time, "sleep", lambda _seconds: None)

    assert hub.renew_ownership("dt-a", 7, cfg=cfg) == {
        "holder": "tm_a",
        "generation": 7,
    }


def test_fault_takeover_reserves_then_atomically_advances_generation(
    monkeypatch, tmp_path
):
    old_cfg = AppConfig(client="tm_old", server="fake", user="tenant")
    new_cfg = AppConfig(client="tm_new", server="fake", user="tenant")
    root = tmp_path / "hub"
    _install_test_flock(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "_run", _local_remote_runner)
    monkeypatch.setattr(hub, "remote_root", lambda _cfg=None: str(root))
    monkeypatch.setattr(hub, "instance_id", lambda: "old-instance")
    _, _, _, generation = hub._lock_remote(
        "claim", "dt-a", cfg=old_cfg, ttl=hub.OWNERSHIP_LEASE_TTL
    )
    lock = root / "locks" / "dt-a"
    side = root / "ownership" / "dt-a.json"
    expired = 1
    lock.write_text(f"tm_old@{expired}@{generation}\n", encoding="utf-8")
    payload = json.loads(side.read_text(encoding="utf-8"))
    payload.update(renewed_at=expired, expires_at=expired + hub.OWNERSHIP_LEASE_TTL)
    side.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    monkeypatch.setattr(hub, "load_config", lambda: new_cfg)
    monkeypatch.setattr(hub, "instance_id", lambda: "new-instance")
    reserved = hub.reserve_fault_takeover("dt-a", generation)
    assert reserved["takeover"]["status"] == "fencing"

    monkeypatch.setattr(hub, "instance_id", lambda: "old-instance")
    with pytest.raises(SystemExit, match="renewal fenced"):
        hub.renew_ownership("dt-a", generation, cfg=old_cfg)

    monkeypatch.setattr(hub, "instance_id", lambda: "new-instance")
    committed = hub.finish_fault_takeover("dt-a", reserved["request_id"], generation)
    assert committed["holder"] == "tm_new"
    assert committed["generation"] == generation + 1
    final = json.loads(side.read_text(encoding="utf-8"))
    assert final["takeover"]["status"] == "committed"
    assert lock.read_text(encoding="utf-8").startswith("tm_new@") and lock.read_text(
        encoding="utf-8"
    ).rstrip().endswith(f"@{generation + 1}")


def test_expired_legacy_lock_can_migrate_through_reserved_fault_takeover(
    monkeypatch, tmp_path
):
    cfg = AppConfig(client="tm_new", server="fake", user="tenant")
    root = tmp_path / "hub"
    _install_test_flock(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "_run", _local_remote_runner)
    monkeypatch.setattr(hub, "remote_root", lambda _cfg=None: str(root))
    monkeypatch.setattr(hub, "load_config", lambda: cfg)
    monkeypatch.setattr(hub, "instance_id", lambda: "new-instance")
    (root / "locks").mkdir(parents=True)
    (root / "locks" / "dt-a").write_text("tm_old@1@7\n", encoding="utf-8")

    reserved = hub.reserve_fault_takeover("dt-a", 7)
    committed = hub.finish_fault_takeover("dt-a", reserved["request_id"], 7)

    assert committed["holder"] == "tm_new"
    assert committed["generation"] == 8
    sidecar = json.loads((root / "ownership" / "dt-a.json").read_text())
    assert sidecar["lease_protocol"] == 2


def test_read_repairs_committed_fault_sidecar_when_lock_publish_was_interrupted(
    monkeypatch, tmp_path
):
    cfg = AppConfig(client="tm_new", server="fake", user="tenant")
    root = tmp_path / "hub"
    _install_test_flock(monkeypatch, tmp_path)
    monkeypatch.setattr(hub, "_run", _local_remote_runner)
    monkeypatch.setattr(hub, "remote_root", lambda _cfg=None: str(root))
    monkeypatch.setattr(hub, "instance_id", lambda: "new-instance")
    (root / "locks").mkdir(parents=True)
    (root / "ownership").mkdir(parents=True)
    (root / "locks" / "dt-a").write_text("tm_old@1@7\n", encoding="utf-8")
    (root / "ownership" / "dt-a.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "lease_protocol": 2,
                "lease_ttl": hub.OWNERSHIP_LEASE_TTL,
                "name": "dt-a",
                "holder": "tm_new",
                "instance_id": "new-instance",
                "generation": 8,
                "renewed_at": 1,
                "takeover": {
                    "status": "committed",
                    "request_id": "fault-1",
                    "claimant": "tm_new",
                    "claimant_instance_id": "new-instance",
                    "previous_holder": "tm_old",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    value = hub.read_ownership("dt-a", cfg)

    assert value["generation"] == 8
    assert (root / "locks" / "dt-a").read_text().startswith("tm_new@")


def test_fault_reservation_retries_lost_response_with_same_request_id(monkeypatch):
    calls = []

    def reserve(_name, _action, *, request_id, generation, cfg=None):
        calls.append((request_id, generation))
        if len(calls) == 1:
            raise SystemExit("response lost")
        return {"ok": True, "code": "idempotent", "generation": generation}

    monkeypatch.setattr(hub, "_fault_takeover_remote", reserve)

    value = hub.reserve_fault_takeover("dt-a", 7)

    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert value["request_id"] == calls[0][0]


def test_stale_sidecar_never_overrides_v1(monkeypatch):
    sidecar = {
        "holder": "tm_wrong",
        "generation": 2,
        "instance_id": "bad",
        "evidence": {"unsafe": True},
    }

    class Result:
        returncode = 0
        stderr = ""
        stdout = "\n".join(
            [
                "V1 " + base64.b64encode(b"tm_owner@1000@9\n").decode(),
                "V2 " + base64.b64encode(json.dumps(sidecar).encode()).decode(),
            ]
        )

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
