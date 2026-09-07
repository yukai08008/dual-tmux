"""Session ownership facts and side-effect-free resume planning."""

from __future__ import annotations

import subprocess
import time
from typing import Any

from . import hub
from . import tmux as tmux_ops
from .activity import read_evidence
from .config import load_config

SCHEMA = 1
AGENTS = {"opencode", "codex", "claude"}
SHELLS = {"zsh", "bash", "sh", "fish", "dash", "ksh"}
TRANSPORTS = {"ssh", "docker", "tmux"}
EVIDENCE_TTL = 180


def persistence_supported(data: dict, role: str) -> bool:
    """Whether a cross-Client handoff can preserve this side's session store."""
    tool = str((data.get(role) or {}).get("tool") or "opencode")
    if tool == "opencode":
        return True
    # A remote bullet remains in the same SSH/container session store. Native
    # trigger and local-bullet stores are Client-local and are not synced yet.
    return role == "bullet" and bool((data.get("runtime") or {}).get("server"))


def _runtime(pane: str) -> str:
    if not pane or not tmux_ops.has_session(pane):
        return "down"
    command = tmux_ops.pane_command(pane)
    if command in SHELLS:
        return "shell"
    if command in TRANSPORTS:
        return "transport"
    return "agent" if command else "down"


def _local_session_pids(session_id: str) -> list[int] | None:
    if not session_id:
        return []
    try:
        result = subprocess.run(
            ["ps", "ax", "-o", "pid=", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    found: list[int] = []
    for line in result.stdout.splitlines():
        raw = line.strip().split(maxsplit=1)
        if len(raw) == 2 and raw[0].isdigit() and session_id in raw[1]:
            found.append(int(raw[0]))
    return found


def probe_writers(data: dict, side: str) -> dict[str, Any]:
    info = data.get(side) or {}
    sid = str(info.get("session_id") or "")
    tool = str(info.get("tool") or "opencode")
    if tool not in AGENTS or not sid:
        return {"status": "unknown", "count": None, "pids": [], "reason": "missing_session_identity"}
    remote = side == "bullet" and bool((data.get("runtime") or {}).get("server"))
    if remote:
        from .recovery import remote_session_pids

        try:
            pids = remote_session_pids(data)
        except (OSError, SystemExit):
            pids = None
    else:
        pids = _local_session_pids(sid)
    if pids is None:
        return {"status": "unknown", "count": None, "pids": [], "reason": "probe_failed"}
    return {
        "status": "duplicate" if len(pids) > 1 else "ok",
        "count": len(pids),
        "pids": pids,
        "reason": "duplicate_writer" if len(pids) > 1 else "",
    }


def _takeover(lease: dict, sides: dict, writers: dict) -> dict:
    for role in ("trigger", "bullet"):
        writer = writers[role]
        if writer["status"] == "unknown":
            return {"safe": False, "action": "stop", "reason": f"{role}_writer_probe_failed"}
        if writer["status"] == "duplicate":
            return {"safe": False, "action": "stop", "reason": f"{role}_duplicate_writer"}
    if lease["state"] == "foreign":
        for role in ("trigger", "bullet"):
            fact = sides[role]
            if fact["attached"] is not False:
                return {"safe": False, "action": "stop", "reason": f"{role}_attached_or_unknown"}
            if fact["progress"] != "idle":
                return {"safe": False, "action": "stop", "reason": f"{role}_{fact['progress']}"}
        return {"safe": True, "action": "request_handoff", "reason": "foreign_idle_detached"}
    if lease["state"] in {"free", "expired"}:
        return {"safe": True, "action": "claim", "reason": lease["state"]}
    return {"safe": True, "action": "resume", "reason": "already_owned"}


def snapshot(data: dict) -> dict:
    name = str(data.get("name") or "")
    lease = hub.read_ownership(name)
    local_evidence = read_evidence(name)
    evidence = (
        local_evidence
        if lease.get("state") in {"owned", "free", "expired"}
        else lease.get("evidence") or {}
    )
    side_evidence = evidence.get("sides") if isinstance(evidence, dict) else {}
    foreign = lease.get("state") == "foreign"
    sides: dict[str, dict] = {}
    writers: dict[str, dict] = {}
    for role, pane_key in (("trigger", "op"), ("bullet", "run")):
        pane = str(data.get(pane_key) or "")
        ev = (side_evidence or {}).get(role) or {}
        if foreign:
            runtime = str(ev.get("runtime") or "unknown")
            attached = ev.get("attached") if isinstance(ev.get("attached"), bool) else None
            progress = str(ev.get("state") or "unknown")
            writer = ev.get("writers") if isinstance(ev.get("writers"), dict) else {}
            writers[role] = writer or {
                "status": "unknown", "count": None, "pids": [],
                "reason": "foreign_owner_probe_required",
            }
        else:
            runtime = _runtime(pane)
            count = tmux_ops.attached_clients(pane) if pane and tmux_ops.has_session(pane) else 0
            attached = None if count is None else count > 0
            progress = str(ev.get("state") or ("idle" if runtime == "shell" else "unknown"))
            writers[role] = probe_writers(data, role)
        sides[role] = {
            "runtime": runtime,
            "attached": attached,
            "progress": progress,
            "evidence_sampled_at": int(ev.get("sampled_at") or 0),
        }
    result = {
        "schema": SCHEMA,
        "name": name,
        "lease": lease,
        "runtime": {role: sides[role]["runtime"] for role in sides},
        "attached": {role: sides[role]["attached"] for role in sides},
        "progress": {role: sides[role]["progress"] for role in sides},
        "writers": writers,
        "snapshot": {
            "source": lease.get("source") or "local",
            "revision": int(lease.get("generation") or 0),
            "freshness": "fresh" if evidence else "unknown",
            "conflict": bool(lease.get("conflict")),
        },
    }
    result["takeover"] = _takeover(lease, sides, writers)
    sampled_at = int((evidence or {}).get("sampled_at") or 0) if isinstance(evidence, dict) else 0
    if foreign and (not sampled_at or int(time.time()) - sampled_at > EVIDENCE_TTL):
        result["snapshot"]["freshness"] = "stale" if sampled_at else "unknown"
        result["takeover"] = {
            "safe": False, "action": "stop", "reason": "owner_evidence_stale"
        }
    if foreign and result["takeover"]["safe"]:
        unsupported = [
            role for role in ("trigger", "bullet")
            if not persistence_supported(data, role)
        ]
        if unsupported:
            result["takeover"] = {
                "safe": False,
                "action": "stop",
                "reason": f"{unsupported[0]}_snapshot_persistence_unsupported",
            }
    return result


def plan_resume(data: dict) -> dict:
    facts = snapshot(data)
    takeover = facts["takeover"]
    if not all((data.get(role) or {}).get("session_id") for role in ("trigger", "bullet")):
        takeover = {"safe": False, "action": "stop", "reason": "not_a_frozen_dst"}
        facts["takeover"] = takeover
    steps = []
    if takeover["action"] == "request_handoff":
        steps.append("request_handoff")
    elif takeover["action"] == "claim":
        steps.append("claim")
    if takeover["safe"]:
        steps.extend(["prepare", "restore", "verify"])
    return {"schema": SCHEMA, "name": facts["name"], "safe": takeover["safe"], "action": takeover["action"], "reason": takeover["reason"], "steps": steps, "ownership": facts}


def acquire_for_resume(data: dict, plan: dict, *, force: bool = False) -> dict:
    if not plan.get("safe"):
        raise SystemExit(f"[err] resume preflight rejected: {plan.get('reason') or 'unsafe'}")
    lease = plan["ownership"]["lease"]
    if plan["action"] == "request_handoff":
        result = hub.request_handoff(str(data.get("name") or ""), reason="resume")
        request = str((result.get("handoff") or {}).get("request_id") or "")
        if not result.get("ok") or not request:
            raise SystemExit(
                f"[err] handoff request failed: {result.get('code') or 'unknown'}"
            )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = hub.read_ownership(str(data.get("name") or ""))
            if current.get("state") in {"free", "expired"}:
                hub.claim(str(data.get("name") or ""))
                acquired = hub.read_ownership(str(data.get("name") or ""))
                return {
                    "generation": int(acquired.get("generation") or 0),
                    "newly_acquired": True,
                }
            handoff = current.get("handoff") or {}
            if handoff.get("request_id") == request and handoff.get("status") == "rejected":
                raise SystemExit(
                    f"[err] handoff rejected: {handoff.get('reason') or 'owner declined'}"
                )
            time.sleep(0.5)
        raise SystemExit(f"[err] handoff pending ({request}); owner did not release within 30s")
    was_owned = lease.get("state") == "owned"
    hub.claim(str(data.get("name") or ""), force=force)
    current = hub.read_ownership(str(data.get("name") or ""))
    if current.get("state") != "owned" or current.get("holder") != load_config().client:
        raise SystemExit("[err] ownership acquisition could not be verified")
    return {"generation": int(current.get("generation") or 0), "newly_acquired": not was_owned}


def verify_resume(data: dict, token: dict) -> dict:
    name = str(data.get("name") or "")
    current = hub.read_ownership(name)
    expected = int(token.get("generation") or 0)
    if int(current.get("generation") or 0) != expected:
        raise SystemExit("[err] ownership generation changed during resume")
    deadline = time.monotonic() + 5
    writers = {role: probe_writers(data, role) for role in ("trigger", "bullet")}
    while (
        any(value["status"] == "ok" and value["count"] == 0 for value in writers.values())
        and time.monotonic() < deadline
    ):
        time.sleep(0.25)
        writers = {role: probe_writers(data, role) for role in ("trigger", "bullet")}
    bad = [
        role for role, value in writers.items()
        if value["status"] != "ok" or value["count"] != 1
    ]
    if bad:
        raise SystemExit(f"[err] resume writer verification failed: {','.join(bad)}")
    current = hub.read_ownership(name)
    if int(current.get("generation") or 0) != expected:
        raise SystemExit("[err] ownership generation changed during resume")
    return {"generation": expected, "writers": writers}
