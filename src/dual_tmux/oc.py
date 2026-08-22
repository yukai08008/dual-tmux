from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

SES_RE = re.compile(r"ses_[A-Za-z0-9]+")


def db_path() -> Path:
    return Path(os.environ.get("OPENCODE_DB", Path.home() / ".local/share/opencode/opencode.db"))


def persist_root() -> Path:
    raw = os.environ.get("OPENCODE_SESSIONS", "")
    if raw:
        return Path(raw).expanduser()
    return (Path.home() / "sessions" / "opencode").expanduser()


@dataclass
class OcSession:
    session_id: str
    slug: str
    title: str = ""
    directory: str = ""
    tool: str = "opencode"
    model: str = ""
    agent: str = ""


def have_opencode() -> bool:
    import shutil

    return shutil.which("opencode") is not None


def parse_model(raw: str) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        mid = data.get("id") or data.get("modelID") or ""
        provider = data.get("providerID") or data.get("provider") or ""
        if mid and provider:
            return f"{provider}/{mid}"
        return str(mid or provider)
    return str(data)


def _rows_to_sessions(rows) -> list[OcSession]:
    out: list[OcSession] = []
    for row in rows:
        out.append(
            OcSession(
                session_id=row[0],
                slug=row[1],
                title=row[2],
                directory=row[3],
                tool="opencode",
                model=parse_model(row[4]),
                agent=row[5] or "",
            )
        )
    return out


def _query(sql: str, args: tuple = ()) -> list[OcSession]:
    db = db_path()
    if not db.is_file():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return _rows_to_sessions(rows)


_SELECT = """
SELECT id, slug, IFNULL(title,''), directory,
       IFNULL(model,''), IFNULL(agent,'')
FROM session
WHERE time_archived IS NULL
"""


def latest_local(limit: int = 1) -> list[OcSession]:
    return _query(_SELECT + " ORDER BY time_updated DESC LIMIT ?", (limit,))


def by_id(session_id: str) -> OcSession | None:
    rows = _query(_SELECT + " AND id = ? LIMIT 1", (session_id,))
    return rows[0] if rows else None


def by_directory(directory: str) -> OcSession | None:
    if not directory:
        return None
    rows = _query(_SELECT + " AND directory = ? ORDER BY time_updated DESC LIMIT 1", (directory,))
    return rows[0] if rows else None


def id_from_pid(pid: str) -> str:
    if not pid:
        return ""
    result = subprocess.run(["ps", "-p", pid, "-o", "command="], capture_output=True, text=True)
    text = result.stdout or ""
    found = SES_RE.findall(text)
    return found[-1] if found else ""


def from_pane(pid: str, cwd: str, exclude: str = "", fallback: bool = False) -> OcSession | None:
    sid = id_from_pid(pid)
    if sid:
        session = by_id(sid)
        if session:
            return session
    if cwd:
        session = by_directory(cwd)
        if session and session.session_id != exclude:
            return session
    if not fallback:
        return None
    rows = latest_local(8)
    for session in rows:
        if session.session_id != exclude:
            return session
    return None


def remote_query_cmd(container: str = "") -> str:
    sql = (
        "SELECT id, slug, IFNULL(title,''), directory, IFNULL(model,''), IFNULL(agent,'') "
        "FROM session WHERE time_archived IS NULL ORDER BY time_updated DESC LIMIT 1;"
    )
    inner = f'sqlite3 -separator "\\t" ~/.local/share/opencode/opencode.db "{sql}"'
    if container:
        return f"docker exec {container} bash -lc '{inner}'"
    return inner


def wait_latest_local(timeout: int = 20) -> OcSession | None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = latest_local(1)
        if rows:
            return rows[0]
        time.sleep(1)
    return None


def wait_latest_remote(ssh_argv: list[str], container: str = "", timeout: int = 20) -> OcSession | None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        session = latest_remote(ssh_argv, container)
        if session:
            return session
        time.sleep(1)
    return None


def latest_remote(ssh_argv: list[str], container: str = "") -> OcSession | None:
    cmd = ssh_argv + [remote_query_cmd(container)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    line = (result.stdout or "").strip().splitlines()
    if not line:
        return None
    parts = line[0].split("\t")
    if len(parts) < 2:
        return None
    return OcSession(
        session_id=parts[0],
        slug=parts[1],
        title=parts[2] if len(parts) > 2 else "",
        directory=parts[3] if len(parts) > 3 else "",
        tool="opencode",
        model=parse_model(parts[4] if len(parts) > 4 else ""),
        agent=parts[5] if len(parts) > 5 else "",
    )


def empty_side(tool: str = "opencode") -> dict[str, str]:
    from .paneparse import parser_id_for_side

    info = {
        "tool": tool,
        "parser": "",
        "model": "",
        "session_id": "",
        "slug": "",
        "agent": "",
    }
    info["parser"] = parser_id_for_side(info)
    return info


def as_bind(session: OcSession, tool: str = "") -> dict[str, str]:
    from .workpoint import now_iso

    from .paneparse import parser_id_for_side

    info = {
        "tool": tool or session.tool or "opencode",
        "parser": "",
        "model": session.model,
        "session_id": session.session_id,
        "slug": session.slug,
        "agent": session.agent,
        "directory": session.directory,
        "frozen_at": now_iso(),
    }
    info["parser"] = parser_id_for_side(info)
    return info


def resume_cmd(info: dict) -> str:
    tool = info.get("tool") or "opencode"
    sid = info.get("session_id") or ""
    if tool != "opencode":
        raise SystemExit(f"[err] resume for tool={tool} is not implemented")
    if not sid:
        return start_cmd(info)
    return f"opencode --auto -s {sid}"


def start_cmd(info: dict, model: str = "") -> str:
    tool = info.get("tool") or "opencode"
    if tool != "opencode":
        raise SystemExit(f"[err] start for tool={tool} is not implemented")
    chosen = model or info.get("model") or ""
    if chosen:
        return f"opencode --model {chosen}"
    return "opencode"


def side_ready(info: dict | None) -> bool:
    info = info or {}
    return bool(info.get("session_id"))


def is_dst(data: dict) -> bool:
    return side_ready(data.get("trigger")) and side_ready(data.get("bullet"))


def persist_snapshot(info: dict, root: Path | None = None) -> Path | None:
    """Find trigger JSON under ~/sessions/opencode/tm_*/. Never keyed by container."""
    from .identity import legal_source

    slug = (info.get("slug") or "").strip()
    sid = (info.get("session_id") or "").strip()
    if not slug and not sid:
        return None
    base = root or persist_root()
    if not base.is_dir():
        return None
    hits: list[Path] = []
    for source in sorted(base.iterdir()):
        if not source.is_dir() or not legal_source(source.name):
            continue
        if slug:
            candidate = source / f"{slug}.json"
            if candidate.is_file():
                hits.append(candidate)
                continue
        if not sid:
            continue
        for path in source.glob("*.json"):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if (data.get("info") or {}).get("id") == sid:
                hits.append(path)
                break
    if not hits:
        return None
    return max(hits, key=lambda p: p.stat().st_mtime)


def import_snapshot(path: Path) -> None:
    result = subprocess.run(["opencode", "import", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "opencode import failed").strip().splitlines()
        raise SystemExit(f"[err] opencode import {path.name}: {err[-1] if err else 'failed'}")


def ensure_local(info: dict, *, importer=None) -> bool:
    """Import persist JSON if this Client sqlite lacks the trigger session.

    Returns True if import ran. Bullet must not call this: that sqlite is
    at the jump target, not on this laptop.
    """
    sid = (info.get("session_id") or "").strip()
    if not sid:
        return False
    if by_id(sid):
        return False
    path = persist_snapshot(info)
    if path is None:
        slug = info.get("slug") or "—"
        raise SystemExit(
            f"[err] trigger session {sid} ({slug}) not in local sqlite and no persist JSON "
            f"under {persist_root()}/tm_*/. Pull persist, then dt resume."
        )
    (importer or import_snapshot)(path)
    if not by_id(sid):
        raise SystemExit(f"[err] imported {path.name} but session {sid} still missing")
    return True
