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


def pane_hash(tmux_name: str, start: int = -20) -> str:
    text = tmux_ops.capture_pane(tmux_name, start=start)
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
    """Trigger-pane fingerprint: last 20 lines, strip ANSI, SHA-1."""
    return pane_hash(data.get("op") or "", start=-20)


def sample_line(data: dict) -> str:
    epoch = int(time.time())
    stamp = now_iso().replace(" ", "T")
    name = data.get("name") or ""
    fp = fingerprint(data)
    op_cmd = tmux_ops.pane_command(data.get("op") or "") or "-"
    run_cmd = tmux_ops.pane_command(data.get("run") or "") or "-"
    return f"{epoch} {stamp} {name} {op_cmd} {run_cmd} {fp}"


def ticks_path(data: dict) -> Path:
    op = str(data.get("op") or "")
    if op:
        return home_dir() / "ops" / op / "ticks.log"
    return activity_path()


def persist_ticks_path(source: str, op: str, root: Path | None = None) -> Path:
    from .oc import persist_root

    return (root or persist_root()) / source / "ticks" / f"{op}.log"


def _tick_tenant() -> str:
    from .oc import persist_tenant

    tenant = persist_tenant()
    if tenant:
        return tenant
    try:
        from .config import load_config

        return persist_tenant(load_config().client)
    except (OSError, SystemExit, ValueError):
        return ""


def _last_fingerprint(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    for raw in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        parts = raw.split()
        if len(parts) >= 6 and parts[2] == name:
            return parts[-1]
    return ""


def last_tick_epoch(path: Path, name: str) -> int:
    """Epoch of the last fingerprint-change tick for this tunnel."""
    if not path.is_file():
        return 0
    for raw in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        parts = raw.split()
        if len(parts) >= 6 and parts[2] == name:
            try:
                return int(parts[0])
            except ValueError:
                return 0
    return 0


def source_tick_epoch(
    source: str,
    data: dict,
    *,
    local: str = "",
    root: Path | None = None,
) -> int:
    op = str(data.get("op") or "")
    name = str(data.get("name") or "")
    if not op or not name:
        return 0
    epoch = last_tick_epoch(persist_ticks_path(source, op, root), name)
    if source == local:
        epoch = max(epoch, last_tick_epoch(ticks_path(data), name))
    return epoch


def preferred_source(
    data: dict,
    *,
    local: str = "",
    root: Path | None = None,
) -> str:
    """Pick the tm_* whose trigger fingerprint last changed most recently."""
    from .identity import legal_source
    from .oc import persist_root

    base = root or persist_root()
    sources: list[str] = []
    if base.is_dir():
        sources = [
            path.name
            for path in sorted(base.iterdir())
            if path.is_dir() and legal_source(path.name)
        ]
    if local and legal_source(local) and local not in sources:
        sources.append(local)
    live = [
        (source_tick_epoch(source, data, local=local, root=base), source)
        for source in sources
    ]
    live = [row for row in live if row[0] > 0]
    if not live:
        return ""
    newest = max(epoch for epoch, _source in live)
    winners = [source for epoch, source in live if epoch == newest]
    if local in winners:
        return local
    return min(winners)


def _mirror_ticks(data: dict) -> None:
    op = str(data.get("op") or "")
    src = ticks_path(data)
    tenant = _tick_tenant()
    if not op or not tenant or not src.is_file():
        return
    dest = persist_ticks_path(tenant, op)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def append_sample(data: dict) -> str:
    line = sample_line(data)
    name = str(data.get("name") or "")
    op = str(data.get("op") or "")
    fp = line.split()[-1] if line.split() else ""
    path = activity_path()
    local = ticks_path(data)
    tenant = _tick_tenant()
    last = _last_fingerprint(local, name)
    if not last and tenant and op:
        last = _last_fingerprint(persist_ticks_path(tenant, op), name)
    if fp and last == fp:
        return line
    for target in dict.fromkeys((local, path)):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        rows = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(rows) > MAX_LINES:
            target.write_text("\n".join(rows[-MAX_LINES:]) + "\n", encoding="utf-8")
    _mirror_ticks(data)
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
