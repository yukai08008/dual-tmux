from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from . import tmux as tmux_ops
from .paths import home_dir
from .workpoint import now_iso

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TICKS = 30
MAX_LINES = 10000
EVIDENCE_SCHEMA = 1
STALL_SECONDS = 600

# TUI chrome changes continuously even when the underlying agent is stuck.  Keep
# this deliberately conservative: dropping a line is safe because an unknown
# activity state fails closed; treating chrome as progress is not safe.
_CHROME = (
    re.compile(r"^[\s\u2580-\u259f\u2800-\u28ff■⬝▣.\-_=|/\\]+$"),
    re.compile(
        r"(?:esc interrupt|\btokens?\b|thought:|build ·|ctrl\+c)", re.IGNORECASE
    ),
    re.compile(r"^\s*\d{4}[-/]\d\d[-/]\d\d[ T]\d\d:\d\d(?::\d\d)?\s*$"),
    re.compile(
        r"^\s*(?:poll|working|thinking|loading)(?:[.\u2026]+)?\s*$", re.IGNORECASE
    ),
)


def _agent_phase(text: str, tool: str) -> str:
    if tool == "opencode":
        from .paneparse import parse_pane

        phase = parse_pane(text, "opencode").phase
        if phase in {"running", "idle"}:
            return "working" if phase == "running" else "idle"
    if re.search(
        r"esc(?:ape)?\s+(?:to\s+)?interrupt|\b(?:working|thinking)\b",
        text,
        re.IGNORECASE,
    ):
        return "working"
    tail = "\n".join(text.splitlines()[-8:])
    if re.search(
        r"(?:Build\s+auto|^\s*[❯›>]\s*$)", tail, re.IGNORECASE | re.MULTILINE
    ):
        return "idle"
    return "unknown"


def activity_path() -> Path:
    return home_dir() / "activity.log"


def pane_hash(tmux_name: str) -> str:
    text = tmux_ops.capture_pane(tmux_name, start=-10)
    clean = ANSI.sub("", text)
    return hashlib.sha1(clean.encode("utf-8", "replace")).hexdigest()[:16]


def semantic_text(text: str) -> str:
    """Return stable, user-facing pane text with animated chrome removed."""
    clean = ANSI.sub("", text).replace("\r", "")
    rows: list[str] = []
    for raw in clean.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or any(pattern.search(line) for pattern in _CHROME):
            continue
        # OpenCode-style footer fragments: model name followed only by a
        # duration/spinner changes and carries no semantic progress.
        if re.search(
            r"\b\d+(?:\.\d+)?(?:ms|s|m)\b", line, re.IGNORECASE
        ) and re.search(
            r"[·▣■⬝]", line
        ):
            continue
        rows.append(line)
    return "\n".join(rows[-40:])


def semantic_fingerprint(text: str) -> str:
    return hashlib.sha256(semantic_text(text).encode("utf-8", "replace")).hexdigest()[:24]


def evidence_path(name: str) -> Path:
    return home_dir() / "ownership-evidence" / f"{name}.json"


def read_evidence(name: str) -> dict:
    path = evidence_path(name)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def activity_evidence(
    data: dict, *, now: int | None = None, capture=None
) -> dict:
    """Sample semantic progress for both panes and persist durable evidence."""
    epoch = int(time.time()) if now is None else int(now)
    capture = capture or (lambda pane: tmux_ops.capture_pane(pane, start=-80))
    previous = read_evidence(str(data.get("name") or ""))
    sides: dict[str, dict] = {}
    for role, key in (("trigger", "op"), ("bullet", "run")):
        pane = str(data.get(key) or "")
        prior = (previous.get("sides") or {}).get(role) or {}
        try:
            text = capture(pane) if pane else ""
            tool = str((data.get(role) or {}).get("tool") or "opencode")
            phase = _agent_phase(text, tool)
            fp = semantic_fingerprint(text)
            changed = bool(fp and fp != prior.get("semantic_fingerprint"))
            last_change = epoch if changed else int(prior.get("last_semantic_change_at") or epoch)
            first_sample = int(prior.get("first_sample_at") or epoch)
            count = int(prior.get("sample_count") or 0) + 1
            command = tmux_ops.pane_command(pane) if pane else ""
            attached_count = tmux_ops.attached_clients(pane) if pane else 0
            if not pane or not command:
                state = "idle" if pane and tmux_ops.has_session(pane) else "unknown"
            elif phase == "idle":
                state = "idle"
            elif phase == "working" and epoch - last_change >= STALL_SECONDS:
                state = "stalled"
            elif phase == "working" or changed:
                state = "working"
            elif epoch - last_change >= STALL_SECONDS and command not in {"zsh", "bash", "sh", "fish"}:
                state = "stalled"
            elif command in {"zsh", "bash", "sh", "fish"}:
                state = "idle"
            else:
                state = str(prior.get("state") or "unknown")
            sides[role] = {
                "state": state,
                "semantic_fingerprint": fp,
                "last_semantic_change_at": last_change,
                "sampled_at": epoch,
                "first_sample_at": first_sample,
                "sample_count": count,
                "window_seconds": max(0, epoch - first_sample),
                "probe_status": "ok",
                "runtime": (
                    "down" if not pane or not tmux_ops.has_session(pane)
                    else "shell" if command in {"zsh", "bash", "sh", "fish"}
                    else "transport" if command in {"ssh", "docker"}
                    else "agent"
                ),
                "attached": None if attached_count is None else attached_count > 0,
                "attached_clients": attached_count,
            }
        except (OSError, RuntimeError, subprocess.SubprocessError):
            sides[role] = {
                **prior,
                "state": "unknown",
                "sampled_at": epoch,
                "probe_status": "failed",
            }
    result = {
        "schema": EVIDENCE_SCHEMA,
        "name": str(data.get("name") or ""),
        "sampled_at": epoch,
        "sides": sides,
    }
    try:
        from .ownership import probe_writers

        for role in ("trigger", "bullet"):
            sides[role]["writers"] = probe_writers(data, role)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        for role in ("trigger", "bullet"):
            sides[role]["writers"] = {
                "status": "unknown", "count": None, "pids": [], "reason": "probe_failed"
            }
    path = evidence_path(result["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=".evidence-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    Path(raw).replace(path)
    return result


def fingerprint(data: dict) -> str:
    op = pane_hash(data.get("op") or "")
    run = pane_hash(data.get("run") or "")
    return hashlib.sha1(f"{op}:{run}".encode()).hexdigest()[:16]


def sample_line(data: dict) -> str:
    epoch = int(time.time())
    stamp = now_iso().replace(" ", "T")
    name = data.get("name") or ""
    fp = fingerprint(data)
    op_cmd = tmux_ops.pane_command(data.get("op") or "") or "-"
    run_cmd = tmux_ops.pane_command(data.get("run") or "") or "-"
    return f"{epoch} {stamp} {name} {op_cmd} {run_cmd} {fp}"


def append_sample(data: dict) -> str:
    line = sample_line(data)
    path = activity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(rows) > MAX_LINES:
        path.write_text("\n".join(rows[-MAX_LINES:]) + "\n", encoding="utf-8")
    return line


def frozen_last_ticks(log_text: str, name: str, ticks: int = TICKS) -> bool:
    by_epoch: dict[int, str] = {}
    for line in log_text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        if parts[2] != name:
            continue
        try:
            epoch = int(parts[0])
        except ValueError:
            continue
        by_epoch[epoch] = parts[-1]
    times = sorted(by_epoch)
    if len(times) < ticks:
        return False
    recent = times[-ticks:]
    return len({by_epoch[t] for t in recent}) == 1
