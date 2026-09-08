"""Session ownership facts and side-effect-free resume planning."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import hub
from . import tmux as tmux_ops
from .activity import read_evidence
from .config import load_config
from .paths import ownership_cache_dir

SCHEMA = 1
AGENTS = {"opencode", "codex", "claude"}
SHELLS = {"zsh", "bash", "sh", "fish", "dash", "ksh"}
TRANSPORTS = {"ssh", "docker", "tmux"}
EVIDENCE_TTL = 180
HANDOFF_TAKEOVER_TIMEOUT = 10.0
HANDOFF_POLL_INTERVAL = 0.25
HANDOFF_PREPARE_TIMEOUT = 9


def persistence_supported(data: dict, role: str) -> bool:
    """Whether a cross-Client handoff can preserve this side's session store."""
    tool = str((data.get(role) or {}).get("tool") or "opencode")
    if tool in AGENTS:
        return True
    # Unknown tools are only safe when a remote bullet remains in the same
    # SSH/container store and therefore does not need Client-local migration.
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
        return {
            "status": "unknown",
            "count": None,
            "pids": [],
            "reason": "missing_session_identity",
        }
    remote = side == "bullet" and bool((data.get("runtime") or {}).get("server"))
    if remote:
        from .recovery import remote_session_pids

        try:
            pids = remote_session_pids(data)
        except (OSError, SystemExit):
            pids = None
    else:
        pids = _local_session_pids(sid)
    if pids == [] and tool == "opencode":
        from . import oc as oc_ops

        pane = str(data.get("run" if side == "bullet" else "op") or "")
        pane_info = tmux_ops.pane_info(pane)
        if remote:
            from .cli import _ssh_argv

            runtime = data.get("runtime") or {}
            session = oc_ops.active_remote(
                _ssh_argv(data), str(runtime.get("container") or "")
            )
        else:
            session = oc_ops.from_pane(
                str(pane_info.get("pid") or ""),
                str(pane_info.get("cwd") or ""),
                fallback=pane_info.get("cmd") == "opencode",
            )
        if session and session.session_id == sid:
            raw_pid = pane_info.get("pid") or "0"
            pids = [int(raw_pid)] if str(raw_pid).isdigit() else [0]
    if pids is None:
        return {
            "status": "unknown",
            "count": None,
            "pids": [],
            "reason": "probe_failed",
        }
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
            return {
                "safe": False,
                "action": "stop",
                "reason": f"{role}_writer_probe_failed",
            }
        if writer["status"] == "duplicate":
            return {
                "safe": False,
                "action": "stop",
                "reason": f"{role}_duplicate_writer",
            }
    if lease["state"] == "foreign":
        for role in ("trigger", "bullet"):
            fact = sides[role]
            # An explicit resume asks the owner daemon to persist and park its
            # panes. A known attached client is safe to detach after idle and
            # writer checks pass; only an unknown attachment probe is unsafe.
            if fact["attached"] is None:
                return {
                    "safe": False,
                    "action": "stop",
                    "reason": f"{role}_attachment_unknown",
                }
            if fact["progress"] != "idle":
                return {
                    "safe": False,
                    "action": "stop",
                    "reason": f"{role}_{fact['progress']}",
                }
        return {
            "safe": True,
            "action": "request_handoff",
            "reason": "foreign_idle_detached",
        }
    if lease["state"] in {"free", "expired"}:
        return {"safe": True, "action": "claim", "reason": lease["state"]}
    return {"safe": True, "action": "resume", "reason": "already_owned"}


def snapshot(data: dict, *, lease: dict | None = None) -> dict:
    name = str(data.get("name") or "")
    lease = lease or hub.read_ownership(name)
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
            attached = (
                ev.get("attached") if isinstance(ev.get("attached"), bool) else None
            )
            progress = str(ev.get("state") or "unknown")
            writer = ev.get("writers") if isinstance(ev.get("writers"), dict) else {}
            writers[role] = writer or {
                "status": "unknown",
                "count": None,
                "pids": [],
                "reason": "foreign_owner_probe_required",
            }
        else:
            runtime = _runtime(pane)
            count = (
                tmux_ops.attached_clients(pane)
                if pane and tmux_ops.has_session(pane)
                else 0
            )
            attached = None if count is None else count > 0
            progress = str(
                ev.get("state") or ("idle" if runtime == "shell" else "unknown")
            )
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
    from . import native_persist

    result["native_snapshots"] = {
        role: native_persist.inspect_session(data.get(role) or {})
        for role in ("trigger", "bullet")
    }
    result["takeover"] = _takeover(lease, sides, writers)
    conflicts = [
        role
        for role, state in result["native_snapshots"].items()
        if state.get("status") == "conflict"
    ]
    if conflicts:
        result["takeover"] = {
            "safe": False,
            "action": "stop",
            "reason": f"{conflicts[0]}_native_snapshot_conflict",
        }
    sampled_at = (
        int((evidence or {}).get("sampled_at") or 0)
        if isinstance(evidence, dict)
        else 0
    )
    if foreign and (not sampled_at or int(time.time()) - sampled_at > EVIDENCE_TTL):
        result["snapshot"]["freshness"] = "stale" if sampled_at else "unknown"
        result["takeover"] = {
            "safe": False,
            "action": "stop",
            "reason": "owner_evidence_stale",
        }
    if foreign and result["takeover"]["safe"]:
        unsupported = [
            role
            for role in ("trigger", "bullet")
            if not persistence_supported(data, role)
        ]
        if unsupported:
            result["takeover"] = {
                "safe": False,
                "action": "stop",
                "reason": f"{unsupported[0]}_snapshot_persistence_unsupported",
            }
    return result


def cache_path(name: str) -> Path:
    return ownership_cache_dir() / f"{name}.json"


def write_cache(facts: dict, *, now: int | None = None) -> Path:
    """Atomically persist facts for read-only Web requests."""
    name = str(facts.get("name") or "")
    if not name or "/" in name or name in {".", ".."}:
        raise ValueError("invalid ownership cache name")
    payload = {
        "cached_at": int(time.time()) if now is None else int(now),
        "facts": facts,
    }
    path = cache_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=".ownership-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(raw).replace(path)
    finally:
        Path(raw).unlink(missing_ok=True)
    return path


def read_cache(name: str, *, now: int | None = None) -> dict:
    """Read cached facts without tmux, process or network probes."""
    path = cache_path(name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {
            "available": False,
            "cached_at": 0,
            "age_seconds": None,
            "freshness": "missing",
            "facts": None,
        }
    cached_at = int(payload.get("cached_at") or 0)
    epoch = int(time.time()) if now is None else int(now)
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else None
    age = max(0, epoch - cached_at) if cached_at else None
    return {
        "available": facts is not None,
        "cached_at": cached_at,
        "age_seconds": age,
        "freshness": "fresh" if age is not None and age <= EVIDENCE_TTL else "stale",
        "facts": facts,
    }


def plan_from_facts(data: dict, facts: dict) -> dict:
    """Build the frozen resume-plan shape from already collected facts."""
    takeover = dict(facts.get("takeover") or {})
    if not all(
        (data.get(role) or {}).get("session_id") for role in ("trigger", "bullet")
    ):
        takeover = {"safe": False, "action": "stop", "reason": "not_a_frozen_dst"}
    steps: list[str] = []
    if takeover.get("action") == "request_handoff":
        steps.append("request_handoff")
    elif takeover.get("action") == "claim":
        steps.append("claim")
    if takeover.get("safe"):
        steps.extend(["prepare", "restore", "verify"])
    return {
        "schema": SCHEMA,
        "name": str(facts.get("name") or data.get("name") or ""),
        "safe": bool(takeover.get("safe")),
        "action": str(takeover.get("action") or "stop"),
        "reason": str(takeover.get("reason") or "facts_unavailable"),
        "steps": steps,
        "ownership": facts,
    }


def plan_resume(data: dict) -> dict:
    facts = snapshot(data)
    plan = plan_from_facts(data, facts)
    facts["takeover"] = {
        "safe": plan["safe"],
        "action": plan["action"],
        "reason": plan["reason"],
    }
    return plan


def _claim_after_service_fence(data: dict, lease: dict) -> dict:
    """Reserve, clean, then atomically publish a new Hub generation."""
    name = str(data.get("name") or "")
    generation = int(lease.get("generation") or 0)
    reservation = hub.reserve_fault_takeover(name, generation)
    request_id = str(reservation.get("request_id") or "")
    try:
        if (data.get("runtime") or {}).get("server"):
            from .recovery import fence_remote_bullet

            fenced = fence_remote_bullet(data)
            if fenced is None:
                raise SystemExit(
                    "[err] service-side cleanup could not be verified; "
                    "ownership was not changed"
                )
        acquired = hub.finish_fault_takeover(name, request_id, generation)
    except BaseException:
        cancellation = None
        try:
            cancellation = hub.cancel_fault_takeover(name, request_id, generation)
        except (OSError, SystemExit):
            pass
        if cancellation and cancellation.get("code") == "already_committed":
            return {
                "holder": str(cancellation.get("holder") or load_config().client),
                "generation": int(cancellation.get("generation") or 0),
            }
        raise
    return {
        "holder": str(acquired.get("holder") or load_config().client),
        "generation": int(acquired.get("generation") or 0),
    }


def acquire_for_resume(data: dict, plan: dict, *, force: bool = False) -> dict:
    if not plan.get("safe"):
        raise SystemExit(
            f"[err] resume preflight rejected: {plan.get('reason') or 'unsafe'}"
        )
    lease = plan["ownership"]["lease"]
    if plan["action"] == "request_handoff":
        deadline = time.monotonic() + HANDOFF_TAKEOVER_TIMEOUT
        result = hub.request_handoff(
            str(data.get("name") or ""),
            reason="resume",
            timeout=HANDOFF_PREPARE_TIMEOUT,
            generation=int(lease.get("generation") or 0),
        )
        request = str((result.get("handoff") or {}).get("request_id") or "")
        if not result.get("ok") or not request:
            raise SystemExit(
                f"[err] handoff request failed: {result.get('code') or 'unknown'}"
            )
        # One deadline covers request acknowledgement, owner-side durable
        # persist/park/release, and the claimant's generation claim.  Never
        # steal first and wait for a later minute tick: that opens two live
        # Trigger panes and cannot prove that the old foreground attach exited.
        while time.monotonic() < deadline:
            current = hub.read_ownership(str(data.get("name") or ""))
            if (
                current.get("state") == "owned"
                and current.get("holder") == load_config().client
            ):
                return {
                    "generation": int(current.get("generation") or 0),
                    "newly_acquired": True,
                }
            if current.get("state") in {"free", "expired"}:
                acquired = (
                    _claim_after_service_fence(data, current)
                    if current.get("state") == "expired"
                    else hub.claim_generation(str(data.get("name") or ""))
                )
                return {
                    "generation": int(acquired.get("generation") or 0),
                    "newly_acquired": True,
                }
            handoff = current.get("handoff") or {}
            if (
                handoff.get("request_id") == request
                and handoff.get("status") == "rejected"
            ):
                raise SystemExit(
                    f"[err] handoff rejected: {handoff.get('reason') or 'owner declined'}"
                )
            time.sleep(HANDOFF_POLL_INTERVAL)
        cancelled = hub.cancel_handoff(
            str(data.get("name") or ""),
            request,
            int(lease.get("generation") or 0),
        )
        if not cancelled.get("ok"):
            # The owner may have crossed the atomic commit point—or completed
            # the transfer—between our last poll and cancel.  Reconcile once;
            # never report a timeout after this Client already became owner.
            current = hub.read_ownership(str(data.get("name") or ""))
            if (
                current.get("state") == "owned"
                and current.get("holder") == load_config().client
            ):
                return {
                    "generation": int(current.get("generation") or 0),
                    "newly_acquired": True,
                }
            if cancelled.get("code") == "too_late" and current.get("state") in {
                "free",
                "expired",
            }:
                acquired = (
                    _claim_after_service_fence(data, current)
                    if current.get("state") == "expired"
                    else hub.claim_generation(str(data.get("name") or ""))
                )
                return {
                    "generation": int(acquired.get("generation") or 0),
                    "newly_acquired": True,
                }
        raise SystemExit(
            "[err] handoff timed out before the old Trigger was persisted and "
            "parked; ownership was not changed"
        )
    was_owned = lease.get("state") == "owned"
    if lease.get("state") == "expired":
        _claim_after_service_fence(data, lease)
    elif lease.get("state") == "free":
        hub.claim_generation(str(data.get("name") or ""))
    else:
        hub.claim(str(data.get("name") or ""), force=force)
    current = hub.read_ownership(str(data.get("name") or ""))
    if current.get("state") != "owned" or current.get("holder") != load_config().client:
        raise SystemExit("[err] ownership acquisition could not be verified")
    return {
        "generation": int(current.get("generation") or 0),
        "newly_acquired": not was_owned,
    }


def verify_resume(data: dict, token: dict) -> dict:
    name = str(data.get("name") or "")
    current = hub.read_ownership(name)
    expected = int(token.get("generation") or 0)
    if int(current.get("generation") or 0) != expected:
        raise SystemExit("[err] ownership generation changed during resume")
    deadline = time.monotonic() + 5
    writers = {role: probe_writers(data, role) for role in ("trigger", "bullet")}
    while (
        any(
            value["status"] == "ok" and value["count"] == 0
            for value in writers.values()
        )
        and time.monotonic() < deadline
    ):
        time.sleep(0.25)
        writers = {role: probe_writers(data, role) for role in ("trigger", "bullet")}
    bad = [
        role
        for role, value in writers.items()
        if value["status"] != "ok" or value["count"] != 1
    ]
    if bad:
        raise SystemExit(f"[err] resume writer verification failed: {','.join(bad)}")
    current = hub.read_ownership(name)
    if int(current.get("generation") or 0) != expected:
        raise SystemExit("[err] ownership generation changed during resume")
    return {"generation": expected, "writers": writers}
