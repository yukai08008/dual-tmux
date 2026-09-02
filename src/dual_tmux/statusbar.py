from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from . import tmux as tmux_ops
from .paths import home_dir

MARKER = "@dt_status"

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# session -> last written chip text; avoids rewriting unchanged status bars.
_applied: dict[str, str] = {}


def busy() -> bool:
    """True while a persist rsync holds its lock dir (same truth as dt web)."""
    locks = home_dir() / "locks"
    return (locks / "persist-tmux").is_dir() or (locks / "persist-opencode").is_dir()


def state_path() -> Path:
    return home_dir() / "hub-sync.json"


def write_state(ok: bool, detail: str = "") -> None:
    """Persist the last hub sync result; atomic write-then-rename."""
    payload = {
        "ok": bool(ok),
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "detail": detail,
    }
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="hub-sync-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def read_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _show(option: str, session: str = "", global_: bool = False) -> str:
    cmd = [tmux_ops.bin(), "show-option", "-qv"]
    if global_:
        cmd.append("-g")
    elif session:
        cmd.extend(["-t", session])
    else:
        return ""
    cmd.append(option)
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def _set(session: str, option: str, value: str) -> None:
    subprocess.run(
        [tmux_ops.bin(), "set-option", "-t", session, option, value],
        capture_output=True,
        check=False,
    )


def chip(
    name: str, state: dict | None, *, syncing: bool = False, frame: int = 0
) -> str:
    short = name.removeprefix("dt-")
    if syncing:
        spin = SPINNER[frame % len(SPINNER)]
        return f"#[fg=yellow]{spin}#[fg=default] dt:{short} 同步中"
    if state is None:
        return f"#[fg=yellow]●#[fg=default] dt:{short} local"
    hhmm = ""
    ts = state.get("ts") or ""
    if len(ts) >= 16:
        hhmm = ts[11:16]
    if state.get("ok"):
        return f"#[fg=green]●#[fg=default] dt:{short} 已同步 {hhmm}".rstrip()
    return f"#[fg=red]●#[fg=default] dt:{short} 同步失败 {hhmm}".rstrip()


def apply(
    session: str,
    name: str,
    state: dict | None,
    *,
    syncing: bool = False,
    frame: int = 0,
) -> bool:
    """Render the dt sync chip into one session's status-right.

    Sessions whose status-right was customized outside dt are left alone.
    """
    if not session or not tmux_ops.has_session(session):
        return False
    current = _show("status-right", session=session)
    glob = _show("status-right", global_=True)
    managed = _show(MARKER, session=session) == "1"
    if not managed and current and current != glob:
        return False
    text = chip(name, state, syncing=syncing, frame=frame)
    if glob:
        text = f"{text} #[dim]|#[default] {glob}"
    if _applied.get(session) == text and managed:
        return True
    _set(session, "status-right", text)
    _set(session, MARKER, "1")
    _applied[session] = text
    return True


def refresh(tunnels: list[dict], hub_enabled: bool = True, *, frame: int = 0) -> int:
    if not tmux_ops.have_tmux():
        return 0
    state = read_state() if hub_enabled else None
    syncing = busy()
    n = 0
    for data in tunnels:
        name = data.get("name") or ""
        for session in (data.get("op") or "", data.get("run") or ""):
            if apply(session, name, state, syncing=syncing, frame=frame):
                n += 1
    return n


def signature(hub_enabled: bool = True) -> tuple:
    """Steady-state signature; daemon skips rewrites while it is unchanged."""
    if not hub_enabled:
        return ("local", busy())
    state = read_state()
    return ("hub", busy(), state.get("ok"), state.get("ts"))
