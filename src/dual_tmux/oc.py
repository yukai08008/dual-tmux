from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path


def db_path() -> Path:
    return Path(os.environ.get("OPENCODE_DB", Path.home() / ".local/share/opencode/opencode.db"))


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


def latest_local(limit: int = 1) -> list[OcSession]:
    db = db_path()
    if not db.is_file():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT id, slug, IFNULL(title,''), directory,
                   IFNULL(model,''), IFNULL(agent,'')
            FROM session
            WHERE time_archived IS NULL
            ORDER BY time_updated DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
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
    return {
        "tool": tool,
        "model": "",
        "session_id": "",
        "slug": "",
        "agent": "",
    }


def as_bind(session: OcSession, tool: str = "") -> dict[str, str]:
    return {
        "tool": tool or session.tool or "opencode",
        "model": session.model,
        "session_id": session.session_id,
        "slug": session.slug,
        "agent": session.agent,
    }


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
