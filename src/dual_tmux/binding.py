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
from datanode.runtime_fsm import BindingEvent, BindingMachine, TunnelProjectionHook

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


def persist_run_entry(session: str, cmd: str) -> None:
    if not session:
        return
    from .store import write_entry

    write_entry(session, cmd)


def proven_payload(data: dict[str, Any], side: str, previous: str) -> dict[str, Any]:
    other = "bullet" if side == "trigger" else "trigger"
    side_info = data.get(side) or {}
    runtime = data.get("runtime") or {}
    candidate = str(side_info.get("session_id") or "")
    payload = {
        "session_id": candidate,
        "tool": str(side_info.get("tool") or "opencode"),
        "directory": str(side_info.get("directory") or ""),
        "other_session_id": str((data.get(other) or {}).get("session_id") or ""),
        "rebuild": bool(previous and candidate and previous != candidate),
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
    return payload


def apply_proven_binding(
    target: dict[str, Any],
    working: dict[str, Any],
    side: str,
    holder: str,
) -> None:
    """Commit a proven working copy through TunnelNode, then project back."""
    hook = TunnelProjectionHook(
        target=target,
        working=working,
        side=side,
        holder=holder,
        persist_entry_fn=persist_run_entry,
    )
    hook.execute()


def run_freeze_attempt(
    data: dict[str, Any],
    side: str,
    tmux_name: str,
    tool: str,
    wait: bool,
    body: Callable[[dict, str, str, str, bool], bool],
) -> bool:
    """Prove on a working copy, then commit the TunnelNode. Original stays put until bound."""
    previous = str((data.get(side) or {}).get("session_id") or "")
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

    working = copy.deepcopy(data)
    ok = body(working, side, tmux_name, tool, wait)
    if not ok:
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

    payload = proven_payload(working, side, previous)
    hook = TunnelProjectionHook(
        target=data,
        working=working,
        side=side,
        holder=holder,
        persist_entry_fn=persist_run_entry,
    )
    machine.register_commit_hook(hook)
    try:
        machine.commit_proven(payload)
    except (TransitionError, ValidationError, ValueError, OSError) as exc:
        if machine.state is BindingAttemptState.PROVING:
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
        session=payload["session_id"],
        rebuild=payload["rebuild"],
        ts=time.time(),
        attempt=attempt_id,
    )
    return True
