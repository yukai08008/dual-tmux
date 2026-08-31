from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

SES_RE = re.compile(r"ses_[A-Za-z0-9]+")


def session_probe_script(session_id: str) -> str:
    """Portable shell expression that checks an OpenCode sqlite session."""
    sid = (session_id or "").strip()
    if not SES_RE.fullmatch(sid):
        return "false"
    code = (
        "import sqlite3,sys; "
        "db=sys.argv[1]; sid=sys.argv[2]; "
        "con=sqlite3.connect('file:'+db+'?mode=ro',uri=True); "
        "raise SystemExit(0 if con.execute("
        "'SELECT 1 FROM session WHERE id=? LIMIT 1',(sid,)).fetchone() else 1)"
    )
    return (
        'db="${OPENCODE_DB:-$HOME/.local/share/opencode/opencode.db}"; '
        f"test -f \"$db\" && python3 -c {shlex.quote(code)} "
        f"\"$db\" {shlex.quote(sid)}"
    )


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


def list_models() -> list[str]:
    if not have_opencode():
        return []
    result = subprocess.run(
        ["opencode", "models"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return []
    out: list[str] = []
    for line in (result.stdout or "").splitlines():
        name = line.strip()
        if name and "/" in name and not name.startswith("opencode "):
            out.append(name)
    return out


def probe_model(model: str, timeout: int = 45) -> tuple[bool, str]:
    model = (model or "").strip()
    if not model:
        return False, "empty model"
    if not have_opencode():
        return False, "opencode not in PATH"
    try:
        result = subprocess.run(
            ["opencode", "run", "--model", model, "reply with ok"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"
    text = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        return False, text[-400:] or f"exit {result.returncode}"
    return True, text[-200:] or "ok"


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


def by_directory(directory: str, created_after_ms: int = 0) -> OcSession | None:
    if not directory:
        return None
    sql = _SELECT + " AND directory = ?"
    args: tuple = (directory,)
    if created_after_ms:
        sql += " AND time_created >= ?"
        args += (created_after_ms,)
    rows = _query(sql + " ORDER BY time_updated DESC LIMIT 1", args)
    return rows[0] if rows else None


def _elapsed_seconds(raw: str) -> int:
    value = (raw or "").strip()
    days = 0
    if "-" in value:
        day, _, value = value.partition("-")
        days = int(day) if day.isdigit() else 0
    parts = [int(x) for x in value.split(":") if x.isdigit()]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = 0, *parts
    else:
        return 0
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _agent_process(pid: str) -> tuple[str, int]:
    """Find the live OpenCode descendant and return command/start epoch ms."""
    queue = [pid]
    seen: set[str] = set()
    while queue and len(seen) < 32:
        current = queue.pop(0)
        if not current or current in seen:
            continue
        seen.add(current)
        result = subprocess.run(
            ["ps", "-p", current, "-o", "command=", "-o", "etime="],
            capture_output=True,
            text=True,
            check=False,
        )
        line = (result.stdout or "").strip()
        command, _, elapsed = line.rpartition(" ")
        tokens = command.split()
        if tokens and Path(tokens[0]).name == "opencode":
            started_ms = int((time.time() - _elapsed_seconds(elapsed)) * 1000)
            return command, started_ms
        children = subprocess.run(
            ["pgrep", "-P", current], capture_output=True, text=True, check=False
        )
        queue.extend(x.strip() for x in children.stdout.splitlines() if x.strip())
    return "", 0


def id_from_pid(pid: str) -> str:
    if not pid:
        return ""
    text, _started_ms = _agent_process(pid)
    found = SES_RE.findall(text)
    return found[-1] if found else ""


def from_pane(pid: str, cwd: str, exclude: str = "", fallback: bool = False) -> OcSession | None:
    command, started_ms = _agent_process(pid)
    found = SES_RE.findall(command)
    sid = found[-1] if found else ""
    if sid:
        session = by_id(sid)
        if session:
            return session
    if cwd and command:
        # OpenCode creates its session lazily on the first prompt.  A session
        # older than this process cannot belong to a fresh blank TUI.
        session = by_directory(cwd, max(0, started_ms - 5000))
        if session and session.session_id != exclude:
            return session
        return None
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


def active_remote(ssh_argv: list[str], container: str = "") -> OcSession | None:
    """Return only the session proven to belong to a live remote OpenCode."""
    code = """import glob,os,sqlite3
me={os.getpid(),os.getppid()}; found=[]
for raw in glob.glob('/proc/[0-9]*/cmdline'):
 try:
  pid=int(raw.split('/')[2])
  if pid in me: continue
  args=[x.decode('utf-8','replace') for x in open(raw,'rb').read().split(b'\\0') if x]
  if not any(os.path.basename(x)=='opencode' or x.endswith('/opencode') for x in args): continue
  sid=''
  for i,x in enumerate(args):
   if x in ('-s','--session') and i+1<len(args): sid=args[i+1]
   elif x.startswith('--session='): sid=x.split('=',1)[1]
  cwd=os.path.realpath('/proc/%s/cwd'%pid)
  found.append((sid,cwd,pid))
 except (OSError,ValueError): pass
db=os.environ.get('OPENCODE_DB',os.path.expanduser('~/.local/share/opencode/opencode.db'))
if not os.path.isfile(db): raise SystemExit(1)
c=sqlite3.connect('file:'+db+'?mode=ro',uri=True)
for sid,cwd,pid in sorted(found,key=lambda x:x[2],reverse=True):
 if sid:
  row=c.execute("SELECT id,slug,IFNULL(title,''),directory,IFNULL(model,''),IFNULL(agent,'') FROM session WHERE id=?",(sid,)).fetchone()
 else:
  row=c.execute("SELECT id,slug,IFNULL(title,''),directory,IFNULL(model,''),IFNULL(agent,'') FROM session WHERE directory=? AND time_archived IS NULL ORDER BY time_updated DESC LIMIT 1",(cwd,)).fetchone()
 if row:
  print('\\t'.join(str(x or '') for x in row)); raise SystemExit(0)
raise SystemExit(1)
"""
    inner = f"python3 -c {shlex.quote(code)}"
    if container:
        inner = f"docker exec {shlex.quote(container)} sh -lc {shlex.quote(inner)}"
    result = subprocess.run([*ssh_argv, inner], capture_output=True, text=True, check=False)
    if result.returncode != 0 or not (result.stdout or "").strip():
        return None
    parts = result.stdout.strip().splitlines()[-1].split("\t")
    if len(parts) < 4:
        return None
    return OcSession(
        session_id=parts[0],
        slug=parts[1],
        title=parts[2],
        directory=parts[3],
        tool="opencode",
        model=parse_model(parts[4] if len(parts) > 4 else ""),
        agent=parts[5] if len(parts) > 5 else "",
    )


def empty_side(tool: str = "opencode") -> dict:
    from .agentclient import empty as empty_agent_client
    from .paneparse import parser_id_for_side

    info = {
        "tool": tool,
        "parser": "",
        "model": "",
        "session_id": "",
        "slug": "",
        "agent": "",
        "agent_client": empty_agent_client(),
    }
    info["parser"] = parser_id_for_side(info)
    return info


def as_bind(session: OcSession, tool: str = "") -> dict:
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
    if tool in {"codex", "claude"}:
        from .agent_sessions import resume_command

        try:
            return resume_command(tool, sid)
        except ValueError as exc:
            raise SystemExit(f"[err] {exc}") from exc
    if tool != "opencode":
        raise SystemExit(f"[err] unsupported resume tool={tool}")
    if not sid:
        return start_cmd(info)
    return f"opencode --auto -s {sid}"


def start_cmd(info: dict, model: str = "") -> str:
    tool = info.get("tool") or "opencode"
    chosen = model or info.get("model") or ""
    if tool in {"codex", "claude"}:
        from .agent_sessions import start_command

        try:
            return start_command(tool, chosen)
        except ValueError as exc:
            raise SystemExit(f"[err] {exc}") from exc
    if tool != "opencode":
        raise SystemExit(f"[err] unsupported start tool={tool}")
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


def ensure_local(info: dict, *, importer=None, role: str = "trigger") -> bool:
    """Import persist JSON if this Client sqlite lacks a local-side session.

    Returns True if import ran. A remote bullet must not call this; a bullet
    whose captured runtime is local uses the same persist recovery as trigger.
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
            f"[err] {role} session {sid} ({slug}) not in local sqlite and no persist JSON "
            f"under {persist_root()}/tm_*/. Pull persist, then dt resume."
        )
    (importer or import_snapshot)(path)
    if not by_id(sid):
        raise SystemExit(f"[err] imported {path.name} but session {sid} still missing")
    return True
