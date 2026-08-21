from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from . import tmux as tmux_ops
from .paths import home_dir
from .workpoint import now_iso

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TICKS = 30
MAX_LINES = 10000


def activity_path() -> Path:
    return home_dir() / "activity.log"


def pane_hash(tmux_name: str) -> str:
    text = tmux_ops.capture_pane(tmux_name, start=-10)
    clean = ANSI.sub("", text)
    return hashlib.sha1(clean.encode("utf-8", "replace")).hexdigest()[:16]


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
