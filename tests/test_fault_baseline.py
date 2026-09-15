from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dual_tmux import hub, oc, recovery
from dual_tmux.config import AppConfig
from dual_tmux.store import save


def _remote_tunnel() -> dict:
    return {
        "name": "dt-fault",
        "op": "op_fault",
        "run": "run_fault",
        "runtime": {
            "server": "box",
            "container": "agent-box",
            "directory": "/workspace",
            "cmd": "ssh box",
        },
        "trigger": {"tool": "opencode", "session_id": "ses_trigger"},
        "bullet": {"tool": "opencode", "session_id": "ses_bullet"},
    }


def test_ssh_timeout_has_stable_unreachable_health_result(monkeypatch):
    monkeypatch.setattr(
        "dual_tmux.cli.require_config",
        lambda: AppConfig(client="tm_test", server="box", user="tester"),
    )

    def timeout(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, timeout=12)

    layers = recovery._remote_probe(_remote_tunnel(), runner=timeout)

    assert layers["transport"]["ok"] is False
    assert layers["transport"]["status"] == "unreachable"
    assert layers["container"]["status"] == "unknown"
    assert layers["session"]["status"] == "unknown"


def test_hub_lock_held_preserves_holder_age_and_generation(monkeypatch):
    result = subprocess.CompletedProcess(
        ["ssh"],
        2,
        stdout="HELD tm_other 7 42\n",
        stderr="",
    )
    monkeypatch.setattr(hub, "_run", lambda *_args, **_kwargs: result)
    config = AppConfig(client="tm_test", server="box", user="tester")

    assert hub._lock_remote("read", "dt-fault", cfg=config) == (
        "HELD",
        "tm_other",
        7,
        42,
    )


def test_missing_recorded_session_never_falls_back_to_another_session(monkeypatch):
    recorded = {
        "tool": "opencode",
        "session_id": "ses_recorded",
        "slug": "recorded",
    }
    looked_up = []
    monkeypatch.setattr(
        oc,
        "by_id",
        lambda session_id: looked_up.append(session_id) or None,
    )
    monkeypatch.setattr(oc, "persist_snapshot", lambda _info: None)
    monkeypatch.setattr(oc, "persist_root", lambda: Path("/persist"))

    with pytest.raises(SystemExit, match="session ses_recorded .* no persist JSON"):
        oc.ensure_local(recorded, role="trigger")

    assert looked_up == ["ses_recorded"]


def test_partial_store_write_is_reported_as_failure(monkeypatch, tmp_path):
    destination = tmp_path / "tunnels" / "dt-fault.json"
    original_write_text = Path.write_text

    def partial_write(path, text, *args, **kwargs):
        original_write_text(path, text[:8], *args, **kwargs)
        raise OSError("injected short write")

    monkeypatch.setattr(Path, "write_text", partial_write)

    with pytest.raises(OSError, match="injected short write"):
        save(
            destination,
            {"name": "dt-fault", "op": "op_fault", "run": "run_fault"},
        )
