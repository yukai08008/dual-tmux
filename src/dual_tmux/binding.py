"""Drive BindingAttempt around freeze/rebuild. Guards stay in the FSM."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from datanode.fsm_core import MemoryStateStore, TransitionError
from datanode.models import (
    AgentRole,
    BindingAttemptNode,
    BindingAttemptState,
    BindingIntent,
)
from datanode.runtime_fsm.binding import BindingEvent, BindingMachine

from . import log as ev


def occupancy_context(tunnel_name: str) -> tuple[str, bool, str]:
    """Return (holder, local_mode, occupancy_holder). Unreadable Hub is local-safe."""
    import os

    try:
        from .config import load_config

        cfg = load_config()
    except (OSError, SystemExit, ValueError):
        return "", True, ""
    holder = str(cfg.client or "")
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return holder, True, ""
    if not cfg.hub_enabled:
        return holder, True, ""
    try:
        from .occupancy import read_occupancy

        occ = read_occupancy(tunnel_name, cfg)
        return holder, False, str(occ.get("holder") or "")
    except (OSError, SystemExit, ValueError):
        return holder, True, ""


def _restore(data: dict[str, Any], snapshot: dict[str, Any]) -> None:
    for key, value in snapshot.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = copy.deepcopy(value)


def run_freeze_attempt(
    data: dict[str, Any],
    side: str,
    tmux_name: str,
    tool: str,
    wait: bool,
    body: Callable[[dict, str, str, str, bool], bool],
) -> bool:
    """Prove, then commit. Failed prove restores the previous binding."""
    keys = (side, "runtime", "run_point", "op_point")
    snapshot = {key: copy.deepcopy(data.get(key)) for key in keys}
    previous = str((data.get(side) or {}).get("session_id") or "")
    other = "bullet" if side == "trigger" else "trigger"
    holder, local_mode, occupancy_holder = occupancy_context(str(data.get("name") or ""))
    attempt_id = f"bind-{data.get('name')}-{side}-{uuid.uuid4().hex[:8]}"
    machine = BindingMachine.create(
        BindingAttemptNode(
            attempt_id=attempt_id,
            tunnel_name=str(data.get("name") or ""),
            role=AgentRole(side),
            intent=BindingIntent.REBUILD if previous else BindingIntent.FREEZE,
            holder=holder,
            previous_session_id=previous,
        ),
        MemoryStateStore(),
    )
    machine.send(
        BindingEvent.REQUESTED,
        {
            "holder": holder,
            "local_mode": local_mode,
            "occupancy_holder": occupancy_holder,
        },
    )
    if not local_mode and occupancy_holder and occupancy_holder != holder:
        machine.send(
            BindingEvent.LIVE_SESSION_MISSING,
            {
                "error": {
                    "code": "occupancy_foreign",
                    "message": f"occupancy holder is {occupancy_holder}",
                }
            },
        )
        ev.emit(
            "freeze.rejected",
            name=data.get("name"),
            side=side,
            error="occupancy_foreign",
            holder=occupancy_holder,
        )
        return False

    ok = body(data, side, tmux_name, tool, wait)
    if not ok:
        _restore(data, snapshot)
        if machine.state is BindingAttemptState.PROVING:
            machine.send(
                BindingEvent.LIVE_SESSION_MISSING,
                {
                    "error": {
                        "code": "live_session_missing",
                        "message": f"no proven {side} session on {tmux_name}",
                    }
                },
            )
        return False

    side_info = data.get(side) or {}
    candidate = str(side_info.get("session_id") or "")
    runtime = data.get("runtime") or {}
    rebuild = bool(previous and candidate and previous != candidate)
    payload = {
        "session_id": candidate,
        "tool": str(side_info.get("tool") or "opencode"),
        "directory": str(side_info.get("directory") or ""),
        "other_session_id": str((data.get(other) or {}).get("session_id") or ""),
        "rebuild": rebuild,
        "endpoint_kind": "",
        "endpoint_server": str(runtime.get("server") or ""),
        "endpoint_container": str(runtime.get("container") or ""),
        "endpoint_directory": str(runtime.get("directory") or ""),
    }
    if side == "bullet":
        if runtime.get("container"):
            payload["endpoint_kind"] = "docker"
        elif runtime.get("server"):
            payload["endpoint_kind"] = "ssh"
        else:
            payload["endpoint_kind"] = "local"
    try:
        machine.send(BindingEvent.LIVE_SESSION_PROVEN, payload)
        machine.send(BindingEvent.COMMIT_SUCCEEDED, {})
    except (TransitionError, ValidationError, ValueError) as exc:
        _restore(data, snapshot)
        if machine.state is BindingAttemptState.COMMITTING:
            machine.send(
                BindingEvent.COMMIT_FAILED,
                {"error": {"code": "commit_rejected", "message": str(exc)}},
            )
        elif machine.state is BindingAttemptState.PROVING:
            machine.send(
                BindingEvent.LIVE_SESSION_MISSING,
                {
                    "error": {
                        "code": "commit_rejected",
                        "message": str(exc),
                    }
                },
            )
        ev.emit(
            "freeze.commit_rejected",
            name=data.get("name"),
            side=side,
            error=str(exc),
        )
        return False
    ev.emit(
        "freeze.bound",
        name=data.get("name"),
        side=side,
        session=candidate,
        rebuild=rebuild,
        ts=time.time(),
        attempt=attempt_id,
    )
    return True
