"""Conservative health state machine and tunnel recovery orchestration."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import hub
from . import log as ev
from . import oc as oc_ops
from . import tmux as tmux_ops
from .paths import home_dir
from .store import find_dt, load, now_iso, save

FAIL_THRESHOLD = 3
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (60, 120, 300, 600, 1800)
CIRCUIT_SECONDS = 300
Runner = Callable[..., subprocess.CompletedProcess]


def state_path(name: str) -> Path:
    return home_dir() / "health" / f"{name}.json"


def _default_state(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "disabled",
        "healthy": False,
        "consecutive_failures": 0,
        "recovery_attempts": 0,
        "next_retry_at": 0,
        "circuit_until": 0,
        "last_checked_at": "",
        "last_healthy_at": "",
        "last_recovery_at": "",
        "last_error": "",
        "layers": {},
    }


def read_state(name: str) -> dict[str, Any]:
    path = state_path(name)
    if not path.is_file():
        return _default_state(name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state(name)
    return {**_default_state(name), **(raw if isinstance(raw, dict) else {})}


def save_state(state: dict[str, Any]) -> Path:
    path = state_path(str(state.get("name") or "unknown"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _layer(ok: bool, status: str, detail: str = "") -> dict[str, Any]:
    return {"ok": bool(ok), "status": status, "detail": detail}


def _remote_command(
    data: dict,
    script: str,
    *,
    runner: Runner,
    input_text: str | None = None,
    use_container: bool = True,
) -> subprocess.CompletedProcess:
    from .cli import _ssh_argv

    container = (data.get("runtime") or {}).get("container") or ""
    command = f"sh -lc {shlex.quote(script)}"
    if container and use_container:
        command = (
            f"docker exec -i {shlex.quote(container)} "
            f"sh -lc {shlex.quote(script)}"
        )
    return runner(
        [*_ssh_argv(data), command],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )


def _remote_probe(
    data: dict, *, runner: Runner = subprocess.run
) -> dict[str, dict[str, Any]]:
    runtime = data.get("runtime") or {}
    container = runtime.get("container") or ""
    directory = runtime.get("directory") or "/workspace"
    bullet = data.get("bullet") or {}
    tool = bullet.get("tool") or "opencode"
    sid = bullet.get("session_id") or ""
    session_line = "echo DT_SESSION=0"
    if sid and tool == "opencode":
        session_line = f"{oc_ops.session_probe_script(sid)}; echo DT_SESSION=$?"
    elif sid and tool in {"codex", "claude"}:
        from .agent_sessions import remote_session_probe_script

        session_line = f"{remote_session_probe_script(tool, sid)}; echo DT_SESSION=$?"
    # Bracket the first character so pgrep cannot match this probe shell's own
    # command line while still matching the real Agent command.
    process_tool = f"[{tool[0]}]{tool[1:]}" if tool else "false"
    process_pattern = process_tool
    script = "\n".join(
        [
            "set +e",
            f"test -d {shlex.quote(directory)}; echo DT_DIR=$?",
            f"command -v {shlex.quote(tool)} >/dev/null 2>&1; echo DT_AGENT=$?",
            session_line,
            f"pgrep -f {shlex.quote(process_pattern)} >/dev/null 2>&1; echo DT_PROCESS=$?",
        ]
    )
    try:
        if container:
            container_check = _remote_command(
                data,
                f"docker inspect -f '{{{{.State.Running}}}}' {shlex.quote(container)}",
                runner=runner,
                use_container=False,
            )
            container_ok = (
                container_check.returncode == 0
                and (container_check.stdout or "").strip() == "true"
            )
            if not container_ok:
                detail = (
                    container_check.stderr
                    or container_check.stdout
                    or "container unavailable"
                ).strip()
                transport_ok = container_check.returncode != 255
                return {
                    "transport": _layer(
                        transport_ok,
                        "connected" if transport_ok else "unreachable",
                        detail if not transport_ok else "",
                    ),
                    "container": _layer(
                        False, "stopped" if transport_ok else "unknown", detail
                    ),
                    "directory": _layer(False, "unknown", directory),
                    "agent": _layer(False, "unknown", tool),
                    "session": _layer(False, "unknown", sid),
                }
        result = _remote_command(data, script, runner=runner)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "transport": _layer(False, "unreachable", str(exc)),
            "container": _layer(not container, "unknown"),
            "directory": _layer(False, "unknown", directory),
            "agent": _layer(False, "unknown", tool),
            "session": _layer(False, "unknown", sid),
        }
    values = {}
    for line in (result.stdout or "").splitlines():
        if line.startswith("DT_") and "=" in line:
            key, _, value = line.partition("=")
            values[key] = value.strip()
    transport_ok = result.returncode == 0 or bool(values)
    stderr = (result.stderr or "").strip().splitlines()
    detail = stderr[-1] if stderr else ""
    process_ok = values.get("DT_PROCESS") == "0"
    session_ok = values.get("DT_SESSION") == "0"
    return {
        "transport": _layer(
            transport_ok,
            "connected" if transport_ok else "unreachable",
            detail,
        ),
        "container": _layer(
            transport_ok,
            "running" if container else "not-used",
            container,
        ),
        "directory": _layer(
            values.get("DT_DIR") == "0",
            "present" if values.get("DT_DIR") == "0" else "missing",
            directory,
        ),
        "agent": _layer(
            values.get("DT_AGENT") == "0" and process_ok,
            "running" if process_ok else "stopped",
            tool,
        ),
        "session": _layer(
            session_ok,
            "present" if session_ok else "missing",
            sid,
        ),
    }


def probe_tunnel(
    data: dict, *, runner: Runner = subprocess.run
) -> dict[str, Any]:
    runtime = data.get("runtime") or {}
    remote = bool(runtime.get("server"))
    trigger = data.get("trigger") or {}
    bullet = data.get("bullet") or {}
    op = data.get("op") or ""
    run = data.get("run") or ""
    op_live = bool(op) and tmux_ops.has_session(op)
    run_live = bool(run) and tmux_ops.has_session(run)
    op_cmd = tmux_ops.pane_command(op) if op_live else ""
    run_cmd = tmux_ops.pane_command(run) if run_live else ""
    trigger_tool = trigger.get("tool") or "opencode"
    bullet_tool = bullet.get("tool") or "opencode"
    layers = {
        "tmux_trigger": _layer(
            op_live, "running" if op_live else "missing", op
        ),
        "tmux_bullet": _layer(
            run_live, "running" if run_live else "missing", run
        ),
        "trigger_agent": _layer(
            op_live and op_cmd == trigger_tool,
            "running" if op_cmd == trigger_tool else "stopped",
            op_cmd,
        ),
    }
    if remote:
        connected = run_live and run_cmd in {"ssh", "docker"}
        layers["bullet_pane"] = _layer(
            connected,
            "connected" if connected else "disconnected",
            run_cmd,
        )
        if run_live:
            layers.update(_remote_probe(data, runner=runner))
        else:
            layers.update(
                {
                    "transport": _layer(False, "not-running"),
                    "container": _layer(
                        False, "unknown", runtime.get("container") or ""
                    ),
                    "directory": _layer(
                        False, "unknown", runtime.get("directory") or ""
                    ),
                    "agent": _layer(False, "unknown", bullet_tool),
                    "session": _layer(
                        False, "unknown", bullet.get("session_id") or ""
                    ),
                }
            )
    else:
        layers["bullet_agent"] = _layer(
            run_live and run_cmd == bullet_tool,
            "running" if run_cmd == bullet_tool else "stopped",
            run_cmd,
        )
        if bullet_tool == "opencode" and bullet.get("session_id"):
            present = oc_ops.by_id(bullet["session_id"]) is not None
            layers["session"] = _layer(
                present,
                "present" if present else "missing",
                bullet["session_id"],
            )
        elif bullet_tool in {"codex", "claude"} and bullet.get("session_id"):
            from .agent_sessions import session_exists

            present = session_exists(bullet_tool, bullet["session_id"])
            layers["session"] = _layer(
                present,
                "present" if present else "missing",
                bullet["session_id"],
            )
    healthy = all(item["ok"] for item in layers.values())
    failures = [key for key, item in layers.items() if not item["ok"]]
    return {
        "name": data.get("name") or "",
        "healthy": healthy,
        "status": "healthy" if healthy else "degraded",
        "checked_at": now_iso(),
        "failures": failures,
        "layers": layers,
    }


def ensure_remote_session(
    data: dict, *, runner: Runner = subprocess.run
) -> bool:
    bullet = data.get("bullet") or {}
    sid = bullet.get("session_id") or ""
    if not sid or (bullet.get("tool") or "opencode") != "opencode":
        return False
    if (_remote_probe(data, runner=runner).get("session") or {}).get("ok"):
        return False
    snapshot = oc_ops.persist_snapshot(bullet)
    if snapshot is None:
        raise SystemExit(
            f"[err] bullet session {sid} missing remotely and no local persist JSON"
        )
    directory = (data.get("runtime") or {}).get("directory") or "/workspace"
    script = (
        f"cd {shlex.quote(directory)} || exit 41; "
        "tmp=$(mktemp /tmp/dt-opencode.XXXXXX.json) || exit 42; "
        "trap 'rm -f \"$tmp\"' EXIT; "
        "cat >\"$tmp\"; opencode import \"$tmp\""
    )
    try:
        result = _remote_command(
            data,
            script,
            runner=runner,
            input_text=snapshot.read_text(encoding="utf-8"),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"[err] remote bullet import: {exc}") from exc
    if result.returncode != 0:
        detail = (
            result.stderr or result.stdout or "import failed"
        ).strip().splitlines()
        raise SystemExit(
            f"[err] remote bullet import: {detail[-1] if detail else 'failed'}"
        )
    if not (_remote_probe(data, runner=runner).get("session") or {}).get("ok"):
        raise SystemExit(
            f"[err] remote bullet import did not restore session {sid}"
        )
    ev.emit("recovery.remote_import", name=data.get("name"), session=sid)
    return True


def recover_now(
    data: dict,
    *,
    force: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Recover unhealthy sides under the ownership gate, then verify health."""
    from .cli import _apply_resume_legacy

    hub.require_active(data, force=force)
    before = probe_tunnel(data, runner=runner)
    if before["healthy"]:
        return before
    # The legacy resume path reconnects the recorded transport first and then
    # imports a missing remote OpenCode session.  Importing before reconnect
    # would turn an ordinary outage into a hard failure.
    result = _apply_resume_legacy(data.get("name"), force=force)
    deadline = time.monotonic() + 20
    after = probe_tunnel(result, runner=runner)
    while not after["healthy"] and time.monotonic() < deadline:
        time.sleep(0.5)
        after = probe_tunnel(result, runner=runner)
    ev.emit(
        "recovery.ok" if after["healthy"] else "recovery.fail",
        name=data.get("name"),
        failures=after["failures"],
    )
    return after


def observe(
    data: dict,
    *,
    auto: bool = True,
    now: int | None = None,
    prober: Callable[[dict], dict[str, Any]] = probe_tunnel,
    recoverer: Callable[[dict], dict[str, Any]] = recover_now,
) -> dict[str, Any]:
    epoch = int(time.time()) if now is None else int(now)
    name = data.get("name") or ""
    state = read_state(name)
    result = prober(data)
    state.update(
        last_checked_at=result.get("checked_at") or now_iso(),
        layers=result.get("layers") or {},
    )
    enabled = bool(data.get("auto_recover"))
    if result.get("healthy"):
        state.update(
            status="healthy",
            healthy=True,
            consecutive_failures=0,
            recovery_attempts=0,
            next_retry_at=0,
            circuit_until=0,
            last_healthy_at=state["last_checked_at"],
            last_error="",
        )
        save_state(state)
        return state
    state["healthy"] = False
    state["consecutive_failures"] = (
        int(state.get("consecutive_failures") or 0) + 1
    )
    state["last_error"] = ",".join(result.get("failures") or [])
    state["status"] = (
        "suspect"
        if state["consecutive_failures"] < FAIL_THRESHOLD
        else "degraded"
    )
    if not enabled:
        state["status"] = (
            "disabled"
            if state["consecutive_failures"] < FAIL_THRESHOLD
            else "degraded"
        )
        save_state(state)
        return state
    if not auto or state["consecutive_failures"] < FAIL_THRESHOLD:
        save_state(state)
        return state
    if epoch < int(state.get("circuit_until") or 0):
        state["status"] = "attention"
        save_state(state)
        return state
    if epoch < int(state.get("next_retry_at") or 0):
        save_state(state)
        return state
    state["status"] = "recovering"
    save_state(state)
    try:
        recovered = recoverer(data)
        if not recovered.get("healthy"):
            raise SystemExit(
                ",".join(recovered.get("failures") or ["verification failed"])
            )
        state.update(
            status="healthy",
            healthy=True,
            consecutive_failures=0,
            recovery_attempts=0,
            next_retry_at=0,
            circuit_until=0,
            last_healthy_at=now_iso(),
            last_recovery_at=now_iso(),
            last_error="",
            layers=recovered.get("layers") or state["layers"],
        )
    except SystemExit as exc:
        attempts = int(state.get("recovery_attempts") or 0) + 1
        delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        state.update(
            status="attention" if attempts >= MAX_ATTEMPTS else "degraded",
            recovery_attempts=attempts,
            next_retry_at=epoch + delay,
            circuit_until=(epoch + CIRCUIT_SECONDS if attempts >= MAX_ATTEMPTS else 0),
            last_recovery_at=now_iso(),
            last_error=str(exc),
        )
        ev.emit(
            "recovery.attempt.fail",
            name=name,
            attempt=attempts,
            error=str(exc),
            next_retry_at=state["next_retry_at"],
        )
    save_state(state)
    return state


def set_enabled(name: str, enabled: bool) -> dict:
    path = find_dt(name)
    data = load(path)
    data["auto_recover"] = bool(enabled)
    data["updated_at"] = now_iso()
    save(path, data)
    hub.push_best_effort(wait=True)
    return data
