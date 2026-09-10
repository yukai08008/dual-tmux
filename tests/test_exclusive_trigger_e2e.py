from __future__ import annotations

import os
import pty
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
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
    before = (
        old_binding.read_bytes(),
        durable_old.read_bytes(),
        durable_new.read_bytes(),
    )

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
            state["handoff"] = {
                "protocol": 2,
                "request_id": "req-e2e",
                "status": "pending_v2",
            }
            return {"ok": True, "handoff": dict(state["handoff"])}

    def finish_handoff(_name, _request, generation, **_kwargs):
        assert not tmux.has_session(op_name)
        assert not tmux.has_session(run_name)
        with state_lock:
            assert generation == state["generation"]
            state.update(state="owned", holder="tm_new", generation=4, handoff=None)
            return {"ok": True}

    def begin_handoff(_name, _request, generation, **_kwargs):
        with state_lock:
            assert generation == state["generation"]
            assert state["handoff"]["status"] == "pending_v2"
            state["handoff"]["status"] = "committing"
            return {"ok": True, "handoff": dict(state["handoff"])}

    def claim_generation(_name, force=False):
        pytest.fail("atomic handoff transfer must not issue a second claim")

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
    monkeypatch.setattr(
        cli,
        "freeze_sides",
        lambda _data, sides, _tool, wait=False: {side: True for side in sides},
    )
    monkeypatch.setattr(hotfix, "sync_persist", lambda *_a: None)
    monkeypatch.setattr(hub, "push", lambda *_a: None)
    monkeypatch.setattr(hub, "read_ownership", read_ownership)
    monkeypatch.setattr(
        hub,
        "renew_ownership",
        lambda *_a, **_kw: {"holder": "tm_old", "generation": 3},
    )
    monkeypatch.setattr(hub, "request_handoff", request_handoff)
    monkeypatch.setattr(hub, "begin_handoff", begin_handoff)
    monkeypatch.setattr(hub, "finish_handoff", finish_handoff)
    monkeypatch.setattr(hub, "claim_generation", claim_generation)

    def claim_occupancy(_name, cfg=None):
        with state_lock:
            state.update(state="owned", holder="tm_new", generation=4, handoff=None)
            return {"ok": True, "holder": "tm_new", "generation": 4, "claimed_at": 1}

    def read_occupancy(_name, cfg=None):
        with state_lock:
            return {
                "ok": True,
                "holder": state["holder"],
                "generation": state["generation"],
                "claimed_at": 1,
            }

    monkeypatch.setattr("dual_tmux.occupancy.claim_occupancy", claim_occupancy)
    monkeypatch.setattr("dual_tmux.occupancy.read_occupancy", read_occupancy)

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


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_control_resume_restores_input_ready_trigger_under_ten_seconds(
    monkeypatch, tmp_path: Path
):
    """Cover the complete ControlService handoff -> restore -> input loop."""
    from dual_tmux import (
        activity,
        cli,
        daemon,
        hotfix,
        hub,
        oc,
        opsdir,
        ownership,
        store,
    )
    from dual_tmux.control import ControlService
    from dual_tmux.store import save, tunnels_dir

    old_home = tmp_path / "old-client"
    new_home = tmp_path / "new-client"
    old_binding = old_home / "dt-shared.json"
    new_dt_home = new_home / ".dual-tmux"
    old_home.mkdir()
    new_home.mkdir()
    monkeypatch.setenv("DUAL_TMUX_HOME", str(new_dt_home))

    suffix = f"{os.getpid()}_{time.time_ns()}"
    op_name = f"op_resume_{suffix}"
    run_name = f"run_resume_{suffix}"
    trigger_sid = f"ses_trigger_{uuid.uuid4().hex}"
    bullet_sid = f"ses_bullet_{uuid.uuid4().hex}"
    ready = {
        "trigger": tmp_path / "trigger-ready",
        "bullet": tmp_path / "bullet-ready",
    }
    tunnel = {
        "name": "dt-shared",
        "op": op_name,
        "run": run_name,
        "runtime": {},
        "trigger": {"tool": "opencode", "session_id": trigger_sid},
        "bullet": {"tool": "opencode", "session_id": bullet_sid},
    }
    save(old_binding, tunnel)
    save(tunnels_dir() / "dt-shared.json", tunnel)

    fake_agent_code = (
        "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ready'); "
        "print('FAKE_AGENT_READY',flush=True); "
        "exec(\"for line in sys.stdin:\\n print('INPUT_ACK:'+line.strip(),flush=True)\")"
    )
    monkeypatch.setattr(
        oc,
        "resume_cmd",
        lambda info: (
            f"{shlex.quote(sys.executable)} -u -c {shlex.quote(fake_agent_code)} "
            f"{shlex.quote(str(ready['trigger' if info['session_id'] == trigger_sid else 'bullet']))} "
            f"-s {shlex.quote(info['session_id'])}"
        ),
    )
    monkeypatch.setattr(oc, "ensure_local", lambda *_a, **_kw: False)
    monkeypatch.setattr(opsdir, "prepare", lambda _data: new_home)

    tmux.ensure_session(op_name, cwd=str(old_home))
    tmux.ensure_session(run_name, cwd=str(old_home))
    returned = old_home / "returned-to-shell"
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.environ.pop("TMUX", None)
        os.execl(
            "/bin/sh",
            "sh",
            "-c",
            f"{tmux.bin()} attach -t {op_name}; printf returned > {returned}",
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
            current = dict(state)
        current["evidence"] = {}
        return current

    def request_handoff(_name, **_kwargs):
        with state_lock:
            state["handoff"] = {
                "protocol": 2,
                "request_id": "req-control-resume",
                "status": "pending_v2",
            }
            return {"ok": True, "handoff": dict(state["handoff"])}

    def begin_handoff(_name, _request, generation, **_kwargs):
        with state_lock:
            assert generation == state["generation"]
            state["handoff"]["status"] = "committing"
            return {"ok": True, "handoff": dict(state["handoff"])}

    def finish_handoff(_name, _request, generation, **_kwargs):
        assert not tmux.has_session(op_name)
        assert not tmux.has_session(run_name)
        with state_lock:
            assert generation == state["generation"]
            state.update(state="owned", holder="tm_new", generation=4, handoff=None)
        return {"ok": True, "generation": 4}

    def snapshot(_data, *, lease=None):
        if lease is None:
            return {
                "lease": read_ownership("dt-shared"),
                "takeover": {
                    "safe": True,
                    "action": "request_handoff",
                    "reason": "foreign_idle_detached",
                },
                "native_snapshots": {},
            }
        return {
            "name": "dt-shared",
            "attached": {"trigger": True, "bullet": False},
            "progress": {"trigger": "idle", "bullet": "idle"},
            "writers": {"trigger": {"status": "ok"}, "bullet": {"status": "ok"}},
        }

    monkeypatch.setattr(daemon, "load_config", lambda: old_cfg)
    monkeypatch.setattr(ownership, "load_config", lambda: new_cfg)
    monkeypatch.setattr(activity, "activity_evidence", lambda _data: {})
    monkeypatch.setattr(ownership, "snapshot", snapshot)
    monkeypatch.setattr(
        ownership,
        "probe_writers",
        lambda data, role: {
            "status": "ok",
            "count": int(
                tmux.has_session(data["op" if role == "trigger" else "run"])
                and ready[role].exists()
            ),
            "pids": [],
            "reason": "",
        },
    )
    monkeypatch.setattr(ownership, "write_cache", lambda *_a, **_kw: None)
    monkeypatch.setattr(cli, "_export_local_snapshots", lambda *_a: [])
    monkeypatch.setattr(cli, "_verify_local_snapshot_exports", lambda *_a: None)
    monkeypatch.setattr(
        cli,
        "freeze_sides",
        lambda _data, sides, _tool, wait=False: {side: True for side in sides},
    )
    monkeypatch.setattr(hotfix, "sync_persist", lambda *_a: None)
    monkeypatch.setattr(hub, "push", lambda *_a: None)
    monkeypatch.setattr(hub, "push_best_effort", lambda *_a, **_kw: None)
    monkeypatch.setattr(hub, "read_tunnel_binding", lambda _name: dict(tunnel))
    monkeypatch.setattr(hub, "read_ownership", read_ownership)
    monkeypatch.setattr(
        hub,
        "renew_ownership",
        lambda *_a, **_kw: {"holder": "tm_old", "generation": 3},
    )
    monkeypatch.setattr(hub, "request_handoff", request_handoff)
    monkeypatch.setattr(hub, "begin_handoff", begin_handoff)
    monkeypatch.setattr(hub, "finish_handoff", finish_handoff)
    monkeypatch.setattr(
        hub, "claim_generation", lambda *_a, **_kw: pytest.fail("no claim")
    )

    def claim_occupancy(_name, cfg=None):
        with state_lock:
            state.update(state="owned", holder="tm_new", generation=4, handoff=None)
            return {"ok": True, "holder": "tm_new", "generation": 4, "claimed_at": 1}

    def read_occupancy(_name, cfg=None):
        with state_lock:
            return {
                "ok": True,
                "holder": state["holder"],
                "generation": state["generation"],
                "claimed_at": 1,
            }

    monkeypatch.setattr("dual_tmux.occupancy.claim_occupancy", claim_occupancy)
    monkeypatch.setattr("dual_tmux.occupancy.read_occupancy", read_occupancy)
    monkeypatch.setattr(store, "iter_dt_files", lambda: [old_binding])

    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and tmux.attached_clients(op_name) != 1:
            time.sleep(0.05)
        assert tmux.attached_clients(op_name) == 1

        started = time.monotonic()
        from dual_tmux.occupancy import claim_occupancy as _claim
        _claim("dt-shared")
        daemon.DualTmuxDaemon(ownership_interval=0)._ownership_step(force=True)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not returned.exists():
            time.sleep(0.05)
        result = ControlService().resume("dt-shared").data

        assert result["ownership_generation"] == 4
        assert state["holder"] == "tm_new"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not returned.exists():
            time.sleep(0.05)
        assert returned.read_text(encoding="utf-8") == "returned"
        assert tmux.has_session(op_name)
        assert tmux.has_session(run_name)

        tmux.send_keys(op_name, "control-resume-ready")
        deadline = time.monotonic() + 3
        pane = ""
        while time.monotonic() < deadline:
            pane = tmux.capture_pane(op_name)
            if "INPUT_ACK:control-resume-ready" in pane:
                break
            time.sleep(0.05)
        assert "INPUT_ACK:control-resume-ready" in pane
        assert time.monotonic() - started < ownership.HANDOFF_TAKEOVER_TIMEOUT
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


@pytest.mark.skipif(
    not os.environ.get("DT_REAL_HANDOFF_HUB"),
    reason="set DT_REAL_HANDOFF_HUB to run the isolated SSH Hub gate",
)
def test_real_hub_daemon_handoff_returns_old_shell(monkeypatch, tmp_path: Path):
    """Opt-in release gate using real SSH, daemon logic, tmux and a PTY client."""
    from dual_tmux import activity, hotfix, hub, oc, opsdir, ownership, store
    from dual_tmux.config import write_config
    from dual_tmux.control import ControlService

    server = os.environ["DT_REAL_HANDOFF_HUB"]
    tenant = f"dte2e_{uuid.uuid4().hex[:10]}"
    assert tenant.startswith("dte2e_") and len(tenant) == 16
    tunnel_name = f"dt-e2e-{uuid.uuid4().hex[:8]}"
    suffix = f"{os.getpid()}_{time.time_ns()}"
    op_name = f"op_real_{suffix}"
    run_name = f"run_real_{suffix}"
    trigger_sid = f"ses_Trigger{uuid.uuid4().hex}"
    bullet_sid = f"ses_Bullet{uuid.uuid4().hex}"
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_dt = old_root / ".dual-tmux"
    new_dt = new_root / ".dual-tmux"
    old_root.mkdir()
    new_root.mkdir()
    common_path = os.environ.get("PATH", "")

    def env_for(root: Path, client: str) -> dict[str, str]:
        return {
            **os.environ,
            "HOME": str(root),
            "DUAL_TMUX_HOME": str(root / ".dual-tmux"),
            "DT_CLIENT": client,
            "DT_SERVER": server,
            "DT_USER": tenant,
            "PATH": common_path,
        }

    old_env = env_for(old_root, "tm_e2e_old")
    new_env = env_for(new_root, "tm_e2e_new")
    setup_cfg = AppConfig(client="tm_e2e_old", server=server, user=tenant)
    subprocess.run(
        [
            *hub.ssh_argv(setup_cfg),
            (
                f'mkdir -p "$HOME/{tenant}/sessions/opencode" '
                f'"$HOME/{tenant}/sessions/native"'
            ),
        ],
        check=True,
    )
    tunnel = {
        "name": tunnel_name,
        "op": op_name,
        "run": run_name,
        "runtime": {},
        "trigger": {"tool": "opencode", "session_id": trigger_sid},
        "bullet": {"tool": "opencode", "session_id": bullet_sid},
    }
    for root, dt_home, client in (
        (old_root, old_dt, "tm_e2e_old"),
        (new_root, new_dt, "tm_e2e_new"),
    ):
        monkeypatch.setenv("HOME", str(root))
        monkeypatch.setenv("DUAL_TMUX_HOME", str(dt_home))
        monkeypatch.setenv("DT_CLIENT", client)
        monkeypatch.setenv("DT_SERVER", server)
        monkeypatch.setenv("DT_USER", tenant)
        write_config(AppConfig(client=client, server=server, user=tenant))
        store.save(dt_home / "tunnels" / f"{tunnel_name}.json", tunnel)
        name_path = root / ".config" / "session-persist" / "name"
        name_path.parent.mkdir(parents=True, exist_ok=True)
        name_path.write_text(client + "\n", encoding="utf-8")
        for kind in ("opencode", "native"):
            local = root / "sessions" / kind / client
            local.mkdir(parents=True, exist_ok=True)
            (local / "durability-marker").write_text(
                f"{client}:{kind}\n", encoding="utf-8"
            )
            script = dt_home / "bin" / f"dt-persist-{kind}"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(
                hotfix.persist_script(kind, server, tenant), encoding="utf-8"
            )
            script.chmod(0o755)

    tmux.ensure_session(op_name, cwd=str(old_root))
    tmux.ensure_session(run_name, cwd=str(old_root))
    marker = old_root / "returned-to-shell"
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(old_env)
        os.environ["TERM"] = "xterm-256color"
        os.environ.pop("TMUX", None)
        os.execl(
            "/bin/sh",
            "sh",
            "-c",
            f"{tmux.bin()} attach -t {op_name}; printf returned > {marker}",
        )

    trigger_writer = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", trigger_sid],
        env=old_env,
    )
    bullet_writer = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", bullet_sid],
        env=old_env,
    )
    owner = None
    try:
        os.environ.update(old_env)
        activity.activity_evidence(tunnel)
        activity.activity_evidence(tunnel)
        hub.claim(tunnel_name)
        fake_agent_code = (
            "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ready'); "
            "print('FAKE_AGENT_READY',flush=True); "
            "exec(\"for line in sys.stdin:\\n print('INPUT_ACK:'+line.strip(),flush=True)\")"
        )
        trigger_ready = tmp_path / "real-trigger-ready"
        bullet_ready = tmp_path / "real-bullet-ready"
        monkeypatch.setattr(oc, "ensure_local", lambda *_a, **_kw: False)
        monkeypatch.setattr(
            oc,
            "resume_cmd",
            lambda info: (
                f"{shlex.quote(sys.executable)} -u -c {shlex.quote(fake_agent_code)} "
                f"{shlex.quote(str(trigger_ready if info['session_id'] == trigger_sid else bullet_ready))} "
                f"-s {shlex.quote(info['session_id'])}"
            ),
        )
        monkeypatch.setattr(opsdir, "prepare", lambda _data: new_root)
        monkeypatch.setattr(hub, "push_best_effort", lambda *_a, **_kw: None)
        monkeypatch.setattr(
            ownership,
            "probe_writers",
            lambda _data, role: {
                "status": "ok",
                "count": int(
                    (trigger_ready if role == "trigger" else bullet_ready).exists()
                ),
                "pids": [],
                "reason": "",
            },
        )
        worker_code = (
            "import time; from dual_tmux import hub; "
            "from dual_tmux.config import load_config; "
            "from dual_tmux.daemon import DualTmuxDaemon; "
            "d=DualTmuxDaemon(ownership_interval=0); "
            f"name={tunnel_name!r}; cfg=load_config(); "
            "exec(\"for _ in range(12):\\n d._ownership_step(force=True)\\n if hub.read_ownership(name,cfg).get('holder') != cfg.client: break\\n time.sleep(.2)\")"
        )
        owner = subprocess.Popen([sys.executable, "-c", worker_code], env=old_env)
        os.environ.update(new_env)
        plan = ownership.plan_resume(tunnel)
        assert plan["safe"] is True, plan["reason"]
        assert plan["action"] == "request_handoff"

        started = time.monotonic()
        resumed = ControlService().resume(tunnel_name).data

        assert resumed["ownership_generation"] > int(
            plan["ownership"]["lease"]["generation"]
        )
        assert tmux.has_session(op_name)
        assert tmux.has_session(run_name)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.read_text(encoding="utf-8") == "returned"
        tmux.send_keys(op_name, "real-control-resume-ready")
        deadline = time.monotonic() + 3
        pane = ""
        while time.monotonic() < deadline:
            pane = tmux.capture_pane(op_name)
            if "INPUT_ACK:real-control-resume-ready" in pane:
                break
            time.sleep(0.05)
        assert "INPUT_ACK:real-control-resume-ready" in pane
        elapsed = time.monotonic() - started
        print(f"real control resume input-ready elapsed={elapsed:.3f}s")
        assert elapsed < ownership.HANDOFF_TAKEOVER_TIMEOUT
        lease = hub.read_ownership(tunnel_name)
        assert lease["holder"] == "tm_e2e_new"
        for kind in ("opencode", "native"):
            subprocess.run(
                [str(new_dt / "bin" / f"dt-persist-{kind}"), server, "--wait"],
                env=new_env,
                check=True,
            )
        assert (
            new_root / "sessions" / "opencode" / "tm_e2e_old" / "durability-marker"
        ).read_text(encoding="utf-8") == "tm_e2e_old:opencode\n"
        assert (
            new_root / "sessions" / "native" / "tm_e2e_old" / "durability-marker"
        ).read_text(encoding="utf-8") == "tm_e2e_old:native\n"
    finally:
        if owner is not None:
            owner.terminate()
            try:
                owner.wait(timeout=3)
            except subprocess.TimeoutExpired:
                owner.kill()
        for process in (trigger_writer, bullet_writer):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        tmux.kill_session(op_name)
        tmux.kill_session(run_name)
        os.close(fd)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        cleanup_cfg = AppConfig(client="tm_e2e_new", server=server, user=tenant)
        assert re.fullmatch(r"dte2e_[0-9a-f]{10}", tenant)
        cleanup_code = (
            "import pathlib,re,shutil,sys; n=sys.argv[1]; "
            "assert re.fullmatch(r'dte2e_[0-9a-f]{10}',n); "
            "p=pathlib.Path.home()/n; "
            "shutil.rmtree(p) if p.is_dir() else None"
        )
        cleanup = f"python3 -c {shlex.quote(cleanup_code)} {shlex.quote(tenant)}"
        subprocess.run([*hub.ssh_argv(cleanup_cfg), cleanup], check=False)


@pytest.mark.skipif(
    not os.environ.get("DT_REAL_HANDOFF_HUB"),
    reason="set DT_REAL_HANDOFF_HUB to run the isolated SSH Hub gate",
)
def test_real_hub_fault_takeover_expires_and_commits_within_budget(
    monkeypatch, tmp_path: Path
):
    """Exercise the m7 short lease and reserved generation transfer over SSH."""
    from dual_tmux import hub, ownership, tmux

    server = os.environ["DT_REAL_HANDOFF_HUB"]
    tenant = f"dte2e_{uuid.uuid4().hex[:10]}"
    name = f"dt-fault-{uuid.uuid4().hex[:8]}"
    old_cfg = AppConfig(client="tm_fault_old", server=server, user=tenant)
    new_cfg = AppConfig(client="tm_fault_new", server=server, user=tenant)
    old_home = tmp_path / "fault-old"
    new_home = tmp_path / "fault-new"
    old_home.mkdir()
    new_home.mkdir()
    op_name = f"op_fault_{os.getpid()}_{time.time_ns()}"
    old_session = f"ses_fault_{uuid.uuid4().hex}"
    writer_start = (
        f"nohup bash -c {shlex.quote(f'exec -a {old_session} sleep 30')} "
        ">/dev/null 2>&1 </dev/null &"
    )
    try:
        subprocess.run([*hub.ssh_argv(old_cfg), writer_start], check=True)
        monkeypatch.setenv("DUAL_TMUX_HOME", str(old_home))
        _, _, _, generation = hub._lock_remote(
            "claim", name, cfg=old_cfg, ttl=hub.OWNERSHIP_LEASE_TTL
        )
        monkeypatch.setenv("DUAL_TMUX_HOME", str(new_home))
        monkeypatch.setenv("DT_CLIENT", new_cfg.client)
        monkeypatch.setenv("DT_SERVER", new_cfg.server)
        monkeypatch.setenv("DT_USER", new_cfg.user)
        started = time.monotonic()
        lease = hub.read_ownership(name, new_cfg)
        while lease["state"] != "expired" and time.monotonic() - started < 8:
            time.sleep(0.1)
            lease = hub.read_ownership(name, new_cfg)
        assert lease["state"] == "expired"
        token = ownership._claim_after_service_fence(
            {
                "name": name,
                "runtime": {"server": server},
                "bullet": {"tool": "opencode", "session_id": old_session},
            },
            lease,
        )
        assert token["holder"] == new_cfg.client
        assert token["generation"] == generation + 1
        fake_agent = f"{shlex.quote(sys.executable)} -u -c " + shlex.quote(
            "import sys; print('FAULT_TRIGGER_READY',flush=True); "
            "exec(\"for line in sys.stdin:\\n print('INPUT_ACK:'+line.strip(),flush=True)\")"
        )
        tmux.ensure_agent(op_name, fake_agent, cwd=str(new_home))
        tmux.send_keys(op_name, "fault-takeover-ready")
        pane = ""
        while time.monotonic() - started < ownership.HANDOFF_TAKEOVER_TIMEOUT:
            pane = tmux.capture_pane(op_name)
            if "INPUT_ACK:fault-takeover-ready" in pane:
                break
            time.sleep(0.05)
        assert "INPUT_ACK:fault-takeover-ready" in pane
        elapsed = time.monotonic() - started
        print(f"real fault takeover input-ready elapsed={elapsed:.3f}s")
        assert elapsed < ownership.HANDOFF_TAKEOVER_TIMEOUT
        probe = f"pgrep -f {shlex.quote(f'[{old_session[0]}]{old_session[1:]}')}"
        assert (
            subprocess.run(
                [*hub.ssh_argv(new_cfg), probe],
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            != 0
        )
    finally:
        tmux.kill_session(op_name)
        assert re.fullmatch(r"dte2e_[0-9a-f]{10}", tenant)
        cleanup_cfg = AppConfig(client="tm_fault_new", server=server, user=tenant)
        cleanup_code = (
            "import pathlib,re,shutil,sys; n=sys.argv[1]; "
            "assert re.fullmatch(r'dte2e_[0-9a-f]{10}',n); "
            "p=pathlib.Path.home()/n; "
            "shutil.rmtree(p) if p.is_dir() else None"
        )
        cleanup = f"python3 -c {shlex.quote(cleanup_code)} {shlex.quote(tenant)}"
        subprocess.run([*hub.ssh_argv(cleanup_cfg), cleanup], check=False)
        kill_writer = (
            f"pgrep -f {shlex.quote(f'[{old_session[0]}]{old_session[1:]}')} "
            "| xargs -r kill -9"
        )
        subprocess.run([*hub.ssh_argv(cleanup_cfg), kill_writer], check=False)
