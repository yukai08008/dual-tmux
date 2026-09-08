from __future__ import annotations

import os
import pty
import shutil
import signal
import threading
import time
from pathlib import Path

import pytest

from dual_tmux import tmux
from dual_tmux.config import AppConfig


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_drop_session_returns_foreground_attach_to_shell(tmp_path: Path):
    """Exercise a real foreground tmux client, not just mocked subprocess calls."""
    name = f"dt_e2e_{os.getpid()}_{time.time_ns()}"
    marker = tmp_path / "returned-to-shell"
    tmux.ensure_session(name, cwd=str(tmp_path))
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.environ.pop("TMUX", None)
        os.execl(
            "/bin/sh",
            "sh",
            "-c",
            f"{tmux.bin()} attach -t {name}; printf returned > {marker}",
        )

    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and tmux.attached_clients(name) != 1:
            time.sleep(0.05)
        assert tmux.attached_clients(name) == 1

        assert tmux.drop_session(name) is True

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.read_text(encoding="utf-8") == "returned"
    finally:
        os.close(fd)
        tmux.kill_session(name)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_two_client_handoff_is_exclusive_under_ten_seconds(monkeypatch, tmp_path: Path):
    """Two Client homes share a lease while the old Client uses real tmux."""
    from dual_tmux import activity, cli, daemon, hotfix, hub, ownership, store

    old_home = tmp_path / "old-client"
    new_home = tmp_path / "new-client"
    old_home.mkdir()
    new_home.mkdir()
    old_binding = old_home / "dt-shared.json"
    new_binding = new_home / "dt-shared.json"
    durable_old = old_home / "persist.snapshot"
    durable_new = new_home / "memory.md"

    suffix = f"{os.getpid()}_{time.time_ns()}"
    op_name = f"op_exclusive_{suffix}"
    run_name = f"run_exclusive_{suffix}"
    tunnel = {"name": "dt-shared", "op": op_name, "run": run_name}
    store.save(old_binding, tunnel)
    store.save(new_binding, tunnel)
    durable_old.write_text("session-snapshot\n", encoding="utf-8")
    durable_new.write_text("durable-memory\n", encoding="utf-8")
    before = (old_binding.read_bytes(), durable_old.read_bytes(), durable_new.read_bytes())

    tmux.ensure_session(op_name, cwd=str(old_home))
    tmux.ensure_session(run_name, cwd=str(old_home))
    marker = old_home / "returned-to-shell"
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.environ.pop("TMUX", None)
        os.execl(
            "/bin/sh",
            "sh",
            "-c",
            f"{tmux.bin()} attach -t {op_name}; printf returned > {marker}",
        )

    state_lock = threading.Lock()
    state = {
        "state": "owned",
        "holder": "tm_old",
        "generation": 3,
        "handoff": None,
    }
    old_cfg = AppConfig(client="tm_old", server="hub", user="test")
    new_cfg = AppConfig(client="tm_new", server="hub", user="test")

    def read_ownership(_name, *_args):
        with state_lock:
            return dict(state)

    def request_handoff(_name, **_kwargs):
        with state_lock:
            state["handoff"] = {"request_id": "req-e2e", "status": "pending"}
            return {"ok": True, "handoff": dict(state["handoff"])}

    def decide_handoff(_name, _request, generation, **_kwargs):
        with state_lock:
            assert generation == state["generation"]
            state["handoff"] = {"request_id": "req-e2e", "status": "acked"}
            return {"ok": True}

    def release(_name, *, generation=0):
        with state_lock:
            assert generation == state["generation"]
            state.update(state="free", holder="", handoff=None)

    def claim(_name, force=False):
        assert force is False
        # The claimant must never become writable while either old pane lives.
        assert not tmux.has_session(op_name)
        assert not tmux.has_session(run_name)
        with state_lock:
            assert state["state"] == "free"
            state.update(state="owned", holder="tm_new", generation=4, handoff=None)
        return "tm_new"

    monkeypatch.setattr(store, "iter_dt_files", lambda: [old_binding])
    monkeypatch.setattr(daemon, "load_config", lambda: old_cfg)
    monkeypatch.setattr(ownership, "load_config", lambda: new_cfg)
    monkeypatch.setattr(activity, "activity_evidence", lambda _data: {})
    monkeypatch.setattr(
        ownership,
        "snapshot",
        lambda _data, **_kwargs: {
            "name": "dt-shared",
            "attached": {"trigger": True, "bullet": False},
            "progress": {"trigger": "idle", "bullet": "idle"},
            "writers": {"trigger": {"status": "ok"}, "bullet": {"status": "ok"}},
        },
    )
    monkeypatch.setattr(ownership, "write_cache", lambda *_a, **_kw: None)
    monkeypatch.setattr(cli, "_export_local_snapshots", lambda *_a: [])
    monkeypatch.setattr(cli, "_verify_local_snapshot_exports", lambda *_a: None)
    monkeypatch.setattr(hotfix, "sync_persist", lambda *_a: None)
    monkeypatch.setattr(hub, "push", lambda *_a: None)
    monkeypatch.setattr(hub, "read_ownership", read_ownership)
    monkeypatch.setattr(hub, "request_handoff", request_handoff)
    monkeypatch.setattr(hub, "decide_handoff", decide_handoff)
    monkeypatch.setattr(hub, "release", release)
    monkeypatch.setattr(hub, "claim", claim)

    worker = threading.Thread(
        target=lambda: (
            time.sleep(0.1),
            daemon.DualTmuxDaemon(ownership_interval=0)._ownership_step(force=True),
        )
    )
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and tmux.attached_clients(op_name) != 1:
            time.sleep(0.05)
        assert tmux.attached_clients(op_name) == 1

        plan = {
            "safe": True,
            "action": "request_handoff",
            "ownership": {"lease": dict(state)},
        }
        started = time.monotonic()
        worker.start()
        token = ownership.acquire_for_resume(dict(tunnel), plan)
        elapsed = time.monotonic() - started
        worker.join(timeout=3)

        assert elapsed < ownership.HANDOFF_TAKEOVER_TIMEOUT
        assert token == {"generation": 4, "newly_acquired": True}
        assert state["holder"] == "tm_new"
        assert not tmux.has_session(op_name)
        assert not tmux.has_session(run_name)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.read_text(encoding="utf-8") == "returned"
        assert before == (
            old_binding.read_bytes(),
            durable_old.read_bytes(),
            durable_new.read_bytes(),
        )
        tmux.ensure_session(op_name, cwd=str(new_home))
        assert tmux.has_session(op_name)
    finally:
        tmux.kill_session(op_name)
        tmux.kill_session(run_name)
        os.close(fd)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
