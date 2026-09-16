"""S13/S14: orphan opencode patrol and run-point hygiene.

A tunnel's container may accumulate leaked opencode processes: each resume
whose ``docker exec`` chain dies without SIGTERM leaves the child alive.
The invariant (S13): one tunnel keeps exactly one active pair of agents;
anything else at the run point must be dead. This module scans container run
points, classifies processes, reports ``orphan.*`` events, and cleans on
explicit request or per-tunnel ``auto_orphan_clean``.

Scope: container run points only. A host run point is shared with other
tunnels, so processes there cannot be attributed safely and are never swept.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import log as ev
from .paths import home_dir
from .recovery import _remote_command

GRACE_SECONDS = 600
PATROL_INTERVAL_SECONDS = 3600
Runner = Callable[..., subprocess.CompletedProcess]

_SCAN_SCRIPT = """
tick=$(getconf CLK_TCK 2>/dev/null || echo 100)
up=$(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0)
for p in $(pgrep -f '[o]pencode' 2>/dev/null); do
  args=$(tr '\\0' ' ' </proc/$p/cmdline 2>/dev/null) || continue
  case "$args" in *opencode*) ;; *) continue ;; esac
  case "$args" in *"/proc/uptime"*|*"getconf CLK_TCK"*) continue ;; esac
  st=$(awk '{print $22}' /proc/$p/stat 2>/dev/null) || continue
  age=$(( up - st / tick ))
  echo "PID=$p AGE=$age ARGS=$args"
done
"""

_WRAPPER_MARKERS = ("/proc/uptime", "getconf CLK_TCK")


def _is_wrapper(args: str) -> bool:
    """The exec wrapper running this script matches pgrep via its own text."""
    stripped = args.strip()
    if stripped.startswith(("sh -lc", "sh -c", "/bin/sh", "bash -lc")):
        return True
    return any(marker in stripped for marker in _WRAPPER_MARKERS)


def _kill_script(pids: list[int]) -> str:
    quoted = " ".join(str(p) for p in pids)
    return (
        f"for p in {quoted}; do kill -TERM $p 2>/dev/null || true; done; "
        "sleep 2; "
        f"for p in {quoted}; do kill -KILL $p 2>/dev/null || true; done; "
        "remaining=0; "
        f"for p in {quoted}; do kill -0 $p 2>/dev/null && remaining=$((remaining+1)); done; "
        'printf "REMAINING=%s\\n" "$remaining"'
    )


def _parse_scan(stdout: str) -> list[dict[str, Any]]:
    rows = []
    for line in (stdout or "").splitlines():
        if not line.startswith("PID="):
            continue
        fields: dict[str, str] = {}
        rest = line
        for key in ("PID", "AGE"):
            marker = f"{key}="
            if not rest.startswith(marker):
                break
            value, _, rest = rest[len(marker) :].partition(" ")
            fields[key] = value
        if "PID" not in fields or "AGE" not in fields:
            continue
        args = rest.removeprefix("ARGS=")
        if not str(fields["PID"]).isdigit():
            continue
        rows.append(
            {
                "pid": int(fields["PID"]),
                "age": int(fields["AGE"]) if str(fields["AGE"]).isdigit() else -1,
                "args": args.strip(),
            }
        )
    return rows


def scan(data: dict, *, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Classify opencode processes inside the tunnel's container run point.

    Exactly one process is legal: the newest one referencing the bound
    session id, or when none does, the newest opencode overall (protects an
    interactive TUI). Everything else is a candidate; candidates older than
    the grace window are orphans. Returns {"status": "unavailable"} when the
    run point cannot be inspected.
    """
    runtime = data.get("runtime") or {}
    if not runtime.get("server") or not runtime.get("container"):
        return {"status": "not-applicable", "processes": [], "legal": None, "orphans": []}
    sid = str((data.get("bullet") or {}).get("session_id") or "")
    try:
        result = _remote_command(data, _SCAN_SCRIPT, runner=runner)
    except (OSError, subprocess.SubprocessError):
        return {"status": "unavailable", "processes": [], "legal": None, "orphans": []}
    if result.returncode != 0:
        return {"status": "unavailable", "processes": [], "legal": None, "orphans": []}
    processes = [
        p for p in _parse_scan(result.stdout or "") if not _is_wrapper(p["args"])
    ]
    pool_all = [p for p in processes if p["age"] >= 0]
    bound = [p for p in pool_all if sid and sid in p["args"]]
    pool = bound if bound else pool_all
    legal = min(pool, key=lambda p: p["age"]) if pool else None
    orphans = [p for p in processes if legal is None or p["pid"] != legal["pid"]]
    orphans = [p for p in orphans if p["age"] >= GRACE_SECONDS]
    return {
        "status": "ok",
        "processes": processes,
        "legal": legal,
        "orphans": orphans,
    }


def clean(
    data: dict, orphans: list[dict[str, Any]], *, runner: Runner = subprocess.run
) -> dict[str, Any]:
    """TERM -> grace -> KILL the listed orphans; the legal writer is never touched."""
    pids = [int(p["pid"]) for p in orphans]
    if not pids:
        return {"terminated": [], "killed": [], "remaining": 0}
    name = str(data.get("name") or "")
    try:
        result = _remote_command(data, _kill_script(pids), runner=runner)
    except (OSError, subprocess.SubprocessError) as exc:
        ev.emit("orphan.clean.fail", name=name, error=str(exc))
        return {"terminated": pids, "killed": [], "remaining": len(pids)}
    remaining = 0
    for line in (result.stdout or "").splitlines():
        if line.startswith("REMAINING="):
            tail = line.partition("=")[2].strip()
            remaining = int(tail) if tail.isdigit() else 0
    outcome = {
        "terminated": pids,
        "killed": pids,
        "remaining": remaining,
    }
    if remaining:
        ev.emit(
            "orphan.clean.fail",
            name=name,
            pids=pids,
            remaining=remaining,
            error="processes survived TERM+KILL",
        )
    else:
        ev.emit("orphan.clean.ok", name=name, terminated=pids)
    return outcome


def sweep_run_point(
    data: dict, *, reason: str, runner: Runner = subprocess.run
) -> list[int] | None:
    """S13: kill every opencode in the container before starting a fresh bullet.

    Returns the killed pids, [] when nothing ran, or None when the run point
    could not be inspected (callers must fail closed rather than start a
    duplicate next to unknown processes).
    """
    runtime = data.get("runtime") or {}
    if not runtime.get("server") or not runtime.get("container"):
        return []
    info = scan(data, runner=runner)
    if info["status"] != "ok":
        return None
    pids = [int(p["pid"]) for p in info["processes"]]
    if not pids:
        return []
    _remote_command(data, _kill_script(pids), runner=runner)
    ev.emit(
        "orphan.sweep",
        name=str(data.get("name") or ""),
        reason=reason,
        pids=pids,
    )
    return pids


def foreign_held(data: dict) -> bool:
    """True when another Client holds this tunnel (or occupancy is unreadable)."""
    from . import hub

    if not hub.enabled():
        return False
    from .config import load_config
    from .occupancy import foreign_holder, read_occupancy

    cfg = load_config()
    try:
        occ = read_occupancy(str(data.get("name") or ""), cfg)
    except SystemExit:
        return True
    return foreign_holder(occ, cfg.client)


def patrol(data: dict, *, runner: Runner = subprocess.run) -> dict[str, Any] | None:
    """S14 patrol round for one tunnel: scan, report, and clean when allowed."""
    if foreign_held(data):
        return None
    name = str(data.get("name") or "")
    info = scan(data, runner=runner)
    if info["status"] != "ok":
        return info if info["status"] == "unavailable" else None
    orphans = info["orphans"]
    if orphans:
        ev.emit(
            "orphan.found",
            name=name,
            sev="warn",
            pids=[int(p["pid"]) for p in orphans],
            ages=[int(p["age"]) for p in orphans],
        )
    cleaned: dict[str, Any] | None = None
    if orphans and data.get("auto_orphan_clean"):
        from .oc import is_dst

        if is_dst(data):
            # Frozen DST: scan-only this round.
            return {"status": "ok", "scan": info, "clean": None, "frozen": True}
        cleaned = clean(data, orphans, runner=runner)
    return {"status": "ok", "scan": info, "clean": cleaned, "frozen": False}


def _marker_path() -> Path:
    return home_dir() / "orphan-patrol.json"


def maybe_patrol(
    data: dict,
    *,
    now: int | None = None,
    runner: Runner = subprocess.run,
) -> bool:
    """Run a patrol round for one tunnel at most once per interval."""
    epoch = int(time.time()) if now is None else int(now)
    name = str(data.get("name") or "")
    path = _marker_path()
    marks: dict[str, int] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            marks = {str(k): int(v) for k, v in raw.items() if isinstance(v, int)}
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    if name in marks and epoch - marks[name] < _patrol_interval():
        return False
    marks[name] = epoch
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marks), encoding="utf-8")
    patrol(data, runner=runner)
    return True


def _patrol_interval() -> int:
    raw = os.environ.get("DUAL_TMUX_ORPHAN_PATROL_INTERVAL") or ""
    try:
        value = int(raw)
    except ValueError:
        return PATROL_INTERVAL_SECONDS
    return value if value > 0 else PATROL_INTERVAL_SECONDS
