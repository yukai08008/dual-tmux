from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .opsdir import ops_dir
from .paths import home_dir
from .store import find_dt, load, normalize_dt

SCHEMA = """
CREATE TABLE IF NOT EXISTS note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
    title, body, content='note', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS note_ai AFTER INSERT ON note BEGIN
    INSERT INTO note_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS note_ad AFTER DELETE ON note BEGIN
    INSERT INTO note_fts(note_fts, rowid, title, body)
    VALUES ('delete', old.id, old.title, old.body);
END;
CREATE TRIGGER IF NOT EXISTS note_au AFTER UPDATE ON note BEGIN
    INSERT INTO note_fts(note_fts, rowid, title, body)
    VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO note_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
"""

EMPTY_MEMORY = {
    "facts": {},
    "updated_at": "",
}


def global_memory_path() -> Path:
    return home_dir() / "MEMORY.json"


def agent_dir(name: str, op: str = "") -> Path:
    if op:
        return ops_dir(op)
    data = load(find_dt(name))
    return ops_dir(data["op"])


def agent_memory_path(name: str, op: str = "") -> Path:
    return agent_dir(name, op) / "MEMORY.json"


def agent_sqlite_path(name: str, op: str = "") -> Path:
    return agent_dir(name, op) / "memory.sqlite"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return dict(EMPTY_MEMORY)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return dict(EMPTY_MEMORY)
    if not isinstance(data, dict):
        return dict(EMPTY_MEMORY)
    facts = data.get("facts")
    if not isinstance(facts, dict):
        facts = {}
    return {"facts": facts, "updated_at": str(data.get("updated_at") or "")}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"facts": data.get("facts") or {}, "updated_at": _now()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def ensure_global() -> Path:
    path = global_memory_path()
    if not path.is_file():
        _write_json(path, dict(EMPTY_MEMORY))
    return path


def ensure_agent(name: str, op: str = "") -> tuple[Path, Path]:
    mem = agent_memory_path(name, op)
    db = agent_sqlite_path(name, op)
    if not mem.is_file():
        _write_json(mem, dict(EMPTY_MEMORY))
    connect(db).close()
    return mem, db


def get_memory(name: str | None = None) -> dict[str, Any]:
    if name:
        ensure_agent(name)
        path = agent_memory_path(name)
    else:
        path = ensure_global()
    return _read_json(path)


def peek_memory(name: str | None = None) -> dict[str, Any]:
    """Read memory without creating files; suitable for GET/Web polling."""
    path = agent_memory_path(name) if name else global_memory_path()
    return _read_json(path)


def peek_notes(name: str, *, limit: int = 40) -> list[dict[str, Any]]:
    """Read existing notes without initializing an agent database."""
    path = agent_sqlite_path(name)
    if not path.is_file():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, day, kind, title, body, created_at FROM note "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return _rows(rows)
    finally:
        conn.close()


def put_fact(key: str, value: Any, name: str | None = None) -> dict[str, Any]:
    key = key.strip()
    if not key:
        raise SystemExit("[err] memory key required")
    if name:
        ensure_agent(name)
        path = agent_memory_path(name)
    else:
        path = ensure_global()
    data = _read_json(path)
    data.setdefault("facts", {})[key] = value
    _write_json(path, data)
    return _read_json(path)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def add_note(
    name: str, body: str, *, title: str = "", kind: str = "note", day: str = ""
) -> dict[str, Any]:
    body = body.strip()
    if not body:
        raise SystemExit("[err] note body required")
    ensure_agent(name)
    day = day or _today()
    created = _now()
    conn = connect(agent_sqlite_path(name))
    try:
        cur = conn.execute(
            "INSERT INTO note(day, kind, title, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (day, kind or "note", title, body, created),
        )
        conn.commit()
        row_id = int(cur.lastrowid or 0)
    finally:
        conn.close()
    return {
        "id": row_id,
        "day": day,
        "kind": kind or "note",
        "title": title,
        "body": body,
        "created_at": created,
    }


def _rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def query_notes(
    name: str,
    *,
    day: str = "",
    since: str = "",
    until: str = "",
    q: str = "",
    limit: int = 40,
) -> list[dict[str, Any]]:
    ensure_agent(name)
    conn = connect(agent_sqlite_path(name))
    try:
        if q.strip():
            sql = (
                "SELECT n.id, n.day, n.kind, n.title, n.body, n.created_at "
                "FROM note_fts f JOIN note n ON n.id = f.rowid "
                "WHERE note_fts MATCH ?"
            )
            args: list[Any] = [q.strip()]
            if day:
                sql += " AND n.day = ?"
                args.append(day)
            if since:
                sql += " AND n.day >= ?"
                args.append(since)
            if until:
                sql += " AND n.day <= ?"
                args.append(until)
            sql += " ORDER BY n.id DESC LIMIT ?"
            args.append(limit)
            return _rows(conn.execute(sql, args).fetchall())
        sql = "SELECT id, day, kind, title, body, created_at FROM note WHERE 1=1"
        args = []
        if day:
            sql += " AND day = ?"
            args.append(day)
        if since:
            sql += " AND day >= ?"
            args.append(since)
        if until:
            sql += " AND day <= ?"
            args.append(until)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return _rows(conn.execute(sql, args).fetchall())
    finally:
        conn.close()


def prepare_for_tunnel(data: dict) -> None:
    ensure_global()
    name = data.get("name") or ""
    op = data.get("op") or ""
    if name and op:
        ensure_agent(normalize_dt(name), op)
