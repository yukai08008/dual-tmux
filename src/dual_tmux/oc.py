from __future__ import annotations

import hashlib
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
        f'test -f "$db" && python3 -c {shlex.quote(code)} '
        f'"$db" {shlex.quote(sid)}'
    )


def db_path() -> Path:
    return Path(
        os.environ.get("OPENCODE_DB", Path.home() / ".local/share/opencode/opencode.db")
    )


def bind_session_directory(session_id: str, directory: str) -> bool:
    """Point a local OpenCode session at this Client's workspace directory.

    Trigger follows the operator: after a cross-Client import the snapshot still
    carries the previous machine's absolute home path, which OpenCode then
    FileSystem.access-fails. Persist JSON is left unchanged.
    """
    sid = (session_id or "").strip()
    dest = str(Path(directory).expanduser()) if directory else ""
    if not sid or not dest:
        return False
    db = db_path()
    if not db.is_file():
        return False
    rel = dest.lstrip("/")
    conn = sqlite3.connect(db)
    try:
        cols = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(session)").fetchall()
        }
        assignments = ["directory=?"]
        values: list[str] = [dest]
        if "path" in cols:
            assignments.append("path=?")
            values.append(rel)
        values.append(sid)
        cur = conn.execute(
            f"UPDATE session SET {', '.join(assignments)} WHERE id=?",
            values,
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error:
        return False
    finally:
        conn.close()


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
    # Empty means the host namespace.  A non-empty value is proof that the
    # session database was reached through that Docker container.
    container: str = ""


@dataclass(frozen=True)
class SnapshotRevision:
    path: Path
    session_id: str
    updated_ms: int
    tail_id: str
    message_ids: frozenset[str]
    digest: str


def _discardable_failed_local_messages(
    session_id: str, persisted_ids: frozenset[str]
) -> tuple[str, ...]:
    """Return local-only failed assistant leaves that are safe to merge past.

    OpenCode can leave one assistant row behind after a provider stream timeout.
    The row has no user-visible text or tool part, but its generated id makes a
    later snapshot from another Client look divergent. Import is merge-based,
    so accepting this shape preserves the failed row while advancing the main
    session tail. Anything with user text, tool activity, or descendants stays
    a hard conflict.
    """
    db = db_path()
    if not session_id or not db.is_file():
        return ()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT id, data FROM message WHERE session_id=?", (session_id,)
            ).fetchall()
            missing = [
                (str(mid), raw) for mid, raw in rows if str(mid) not in persisted_ids
            ]
            if not missing:
                return ()
            missing_ids = {mid for mid, _raw in missing}
            for mid, raw in rows:
                try:
                    message = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    return ()
                if str(message.get("parentID") or "") in missing_ids:
                    return ()
            allowed_parts = {"step-start", "step-finish", "reasoning", "text"}
            for mid, raw in missing:
                try:
                    message = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    return ()
                if message.get("role") != "assistant" or not message.get("error"):
                    return ()
                parts = conn.execute(
                    "SELECT data FROM part WHERE session_id=? AND message_id=?",
                    (session_id, mid),
                ).fetchall()
                for (part_raw,) in parts:
                    try:
                        part = json.loads(part_raw)
                    except (TypeError, json.JSONDecodeError):
                        return ()
                    kind = str(part.get("type") or "")
                    if kind not in allowed_parts:
                        return ()
                    if kind == "text" and str(part.get("text") or "").strip():
                        return ()
        finally:
            conn.close()
    except sqlite3.Error:
        return ()
    return tuple(sorted(missing_ids))


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
        check=False,
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
            check=False,
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
            ["ps", "-ww", "-p", current, "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
        command = (result.stdout or "").strip()
        tokens = command.split()
        if tokens and Path(tokens[0]).name == "opencode":
            elapsed_result = subprocess.run(
                ["ps", "-p", current, "-o", "etime="],
                capture_output=True,
                text=True,
                check=False,
            )
            elapsed = (elapsed_result.stdout or "").strip()
            started_ms = int((time.time() - _elapsed_seconds(elapsed)) * 1000)
            return command, started_ms
        children = subprocess.run(
            ["pgrep", "-P", current], capture_output=True, text=True, check=False
        )
        queue.extend(x.strip() for x in children.stdout.splitlines() if x.strip())
    return "", 0


def id_from_pid(pid: str, cwd: str = "") -> str:
    if not pid:
        return ""
    text, _started_ms = _agent_process(pid)
    found = SES_RE.findall(text)
    if found:
        return found[-1]
    if cwd:
        session = from_pane(pid, cwd, fallback=False)
        if session:
            return session.session_id
    return ""


def from_pane(
    pid: str, cwd: str, exclude: str = "", fallback: bool = False
) -> OcSession | None:
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


def wait_latest_remote(
    ssh_argv: list[str], container: str = "", timeout: int = 20
) -> OcSession | None:
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
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
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
if os.path.isdir('/proc'):
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
   # Linux PIDs wrap and may be reused; field 22 is the process start time in
   # clock ticks and is the only reliable ordering key here.
   stat=open('/proc/%s/stat'%pid).read()
   started=int(stat[stat.rfind(')')+2:].split()[19])
   env={}
   for item in open('/proc/%s/environ'%pid,'rb').read().split(b'\\0'):
    key,sep,value=item.partition(b'=')
    if sep: env[key.decode('utf-8','replace')]=value.decode('utf-8','replace')
   db=env.get('OPENCODE_DB') or os.path.join(env.get('HOME','/root'),'.local/share/opencode/opencode.db')
   if os.path.isabs(db): db='/proc/%s/root'%pid+db
   container_id=''
   try:
    cgroup=open('/proc/%s/cgroup'%pid).read()
    import re
    match=re.search(r'(?:docker[-/]|docker/)([0-9a-f]{12,64})(?:\\.scope)?',cgroup)
    if not match: match=re.search(r'/([0-9a-f]{64})(?:\\.scope)?(?:\\n|$)',cgroup)
    if match: container_id=match.group(1)
   except OSError: pass
   found.append((sid,cwd,pid,started,db,container_id))
  except (OSError,ValueError): pass
else:
 import subprocess
 try:
  ps_res=subprocess.run(['ps','-eo','pid,etime,command'],capture_output=True,text=True)
  for line in (ps_res.stdout or '').splitlines():
   parts=line.strip().split(None,2)
   if len(parts)<3: continue
   try: pid=int(parts[0])
   except ValueError: continue
   if pid in me: continue
   etime_str,cmdline=parts[1],parts[2]
   tokens=cmdline.split()
   if not any(os.path.basename(t)=='opencode' or t.endswith('/opencode') for t in tokens): continue
   sid=''
   for i,t in enumerate(tokens):
    if t in ('-s','--session') and i+1<len(tokens): sid=tokens[i+1]
    elif t.startswith('--session='): sid=t.split('=',1)[1]
   cwd=''
   for lsof_cmd in ('lsof','/usr/sbin/lsof'):
    try:
     l_out=subprocess.run([lsof_cmd,'-a','-p',str(pid),'-d','cwd','-Fn'],capture_output=True,text=True).stdout or ''
     for l in l_out.splitlines():
      if l.startswith('n'): cwd=os.path.realpath(l[1:]); break
     if cwd: break
    except Exception: pass
   days=0; raw_etime=etime_str
   if '-' in raw_etime: d,raw_etime=raw_etime.split('-',1); days=int(d)
   p=[int(x) for x in raw_etime.split(':') if x.isdigit()]
   if len(p)==3: sec=days*86400+p[0]*3600+p[1]*60+p[2]
   elif len(p)==2: sec=days*86400+p[0]*60+p[1]
   elif len(p)==1: sec=days*86400+p[0]
   else: sec=0
   started=-sec
   db=os.environ.get('OPENCODE_DB') or os.path.expanduser('~/.local/share/opencode/opencode.db')
   found.append((sid,cwd,pid,started,db,''))
 except Exception: pass
for sid,cwd,pid,started,db,container_id in sorted(found,key=lambda x:x[3],reverse=True):
 try:
  if not os.path.isfile(db): continue
  c=sqlite3.connect('file:'+db+'?mode=ro',uri=True)
  if sid:
   row=c.execute("SELECT id,slug,IFNULL(title,''),directory,IFNULL(model,''),IFNULL(agent,'') FROM session WHERE id=?",(sid,)).fetchone()
  else:
   row=c.execute("SELECT id,slug,IFNULL(title,''),directory,IFNULL(model,''),IFNULL(agent,'') FROM session WHERE directory=? AND parent_id IS NULL AND time_archived IS NULL ORDER BY time_updated DESC LIMIT 1",(cwd,)).fetchone()
  c.close()
  if row:
   print('\\t'.join([*(str(x or '') for x in row),container_id])); raise SystemExit(0)
 except sqlite3.Error: pass
raise SystemExit(1)
"""
    inner = f"python3 -c {shlex.quote(code)}"
    if container:
        inner = f"docker exec {shlex.quote(container)} sh -lc {shlex.quote(inner)}"
    result = subprocess.run(
        [*ssh_argv, inner], capture_output=True, text=True, check=False
    )
    if result.returncode != 0 or not (result.stdout or "").strip():
        return None
    parts = result.stdout.strip().splitlines()[-1].split("\t")
    if len(parts) < 4:
        return None
    discovered_container = container
    container_id = parts[6] if len(parts) > 6 else ""
    if not discovered_container and container_id:
        resolved = subprocess.run(
            [
                *ssh_argv,
                f"docker inspect --format '{{{{.Name}}}}' {shlex.quote(container_id)}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if resolved.returncode != 0 or not (resolved.stdout or "").strip():
            return None
        discovered_container = resolved.stdout.strip().splitlines()[-1].lstrip("/")
    return OcSession(
        session_id=parts[0],
        slug=parts[1],
        title=parts[2],
        directory=parts[3],
        tool="opencode",
        model=parse_model(parts[4] if len(parts) > 4 else ""),
        agent=parts[5] if len(parts) > 5 else "",
        container=discovered_container,
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
    from .paneparse import parser_id_for_side
    from .workpoint import now_iso

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


def _snapshot_revision(path: Path, expected_sid: str = "") -> SnapshotRevision | None:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    info = payload.get("info") or {}
    sid = str(info.get("id") or "").strip()
    if not sid or (expected_sid and sid != expected_sid):
        return None
    updated = (info.get("time") or {}).get("updated") or 0
    try:
        updated_ms = int(updated)
    except (TypeError, ValueError):
        updated_ms = 0
    ids: list[str] = []
    for message in payload.get("messages") or []:
        mid = str((message.get("info") or {}).get("id") or "").strip()
        if mid:
            ids.append(mid)
    return SnapshotRevision(
        path=path,
        session_id=sid,
        updated_ms=updated_ms,
        tail_id=ids[-1] if ids else "",
        message_ids=frozenset(ids),
        digest=hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def resolve_snapshots(
    info: dict, root: Path | None = None, source: str | None = None
) -> tuple[SnapshotRevision, ...]:
    """Resolve every verified per-Client revision for append-only union."""
    from .identity import legal_source

    slug = (info.get("slug") or "").strip()
    sid = (info.get("session_id") or "").strip()
    if not slug and not sid:
        return ()
    base = root or persist_root()
    if not base.is_dir():
        return ()
    hits: set[Path] = set()
    for source_dir in sorted(base.iterdir()):
        if source and source_dir.name != source:
            continue
        if not source_dir.is_dir() or not legal_source(source_dir.name):
            continue
        if slug:
            candidate = source_dir / f"{slug}.json"
            if candidate.is_file():
                hits.add(candidate)
        if not sid:
            continue
        for path in source_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if (data.get("info") or {}).get("id") == sid:
                hits.add(path)
                break
    if not hits:
        return ()
    revisions = [rev for path in hits if (rev := _snapshot_revision(path, sid))]
    if not revisions:
        return ()
    return tuple(sorted(revisions, key=lambda rev: (rev.updated_ms, str(rev.path))))


def resolve_snapshot(info: dict, root: Path | None = None) -> SnapshotRevision | None:
    """Resolve the newest verified per-Client snapshot by payload revision."""
    revisions = resolve_snapshots(info, root)
    if not revisions:
        return None
    with_revision = [rev for rev in revisions if rev.updated_ms > 0]
    if not with_revision:
        # Compatibility for old exports without info.time.updated.
        return max(revisions, key=lambda rev: rev.path.stat().st_mtime)
    newest_ms = max(rev.updated_ms for rev in with_revision)
    newest = [rev for rev in with_revision if rev.updated_ms == newest_ms]
    return min(newest, key=lambda rev: str(rev.path))


def persist_snapshot(info: dict, root: Path | None = None) -> Path | None:
    """Find the freshest verified snapshot; never key it by container name."""
    revision = resolve_snapshot(info, root)
    return revision.path if revision else None


def import_snapshot(path: Path) -> None:
    result = subprocess.run(
        [oc_bin(), "import", str(path)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        err = (
            (result.stderr or result.stdout or "opencode import failed")
            .strip()
            .splitlines()
        )
        raise SystemExit(
            f"[err] opencode import {path.name}: {err[-1] if err else 'failed'}"
        )


OPENCODE_FALLBACK_BINS = (
    "~/.opencode/bin/opencode",
    "/opt/homebrew/bin/opencode",
    "/usr/local/bin/opencode",
)


def oc_bin() -> str:
    """Resolve the opencode binary; cron/launchd run with a minimal PATH."""
    import shutil

    found = shutil.which("opencode")
    if found:
        return found
    for cand in OPENCODE_FALLBACK_BINS:
        path = Path(cand).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return "opencode"


def persist_tenant(default: str = "") -> str:
    """The persist tenant this machine syncs: session-persist name, else default."""
    try:
        name = (
            (Path.home() / ".config" / "session-persist" / "name")
            .read_text(encoding="utf-8")
            .strip()
        )
    except OSError:
        name = ""
    return name or default


def session_updated_ms(session_id: str) -> int | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    db = db_path()
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT time_updated FROM session WHERE id=?", (sid,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return int(row[0]) if row and row[0] else None


def local_tail_message_id(session_id: str) -> str:
    db = db_path()
    if not db.is_file():
        return ""
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT id FROM message WHERE session_id=? ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row else ""


def local_has_message(session_id: str, message_id: str) -> bool:
    if not message_id:
        return True
    db = db_path()
    if not db.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT 1 FROM message WHERE session_id=? AND id=? LIMIT 1",
                (session_id, message_id),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row)


def _local_message_ids(session_id: str) -> frozenset[str]:
    db = db_path()
    if not session_id or not db.is_file():
        return frozenset()
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT id FROM message WHERE session_id=?", (session_id,)
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return frozenset()
    return frozenset(str(row[0]) for row in rows)


def _snapshot_identity_compatible_with_local(
    session_id: str, snapshot_path: Path
) -> bool:
    """Reject only impossible ID collisions before an append-only import.

    OpenCode import inserts missing message/part IDs and preserves rows already
    present locally. Different Clients can therefore safely contribute
    different branches to one session. Shared IDs may legitimately represent
    an earlier in-flight versus later completed record, but their immutable
    graph identity must agree.
    """
    db = db_path()
    if not session_id or not db.is_file():
        return False
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for item in payload.get("messages") or []:
                info = item.get("info") or {}
                mid = str(info.get("id") or "")
                if not mid:
                    return False
                row = conn.execute(
                    "SELECT data FROM message WHERE session_id=? AND id=?",
                    (session_id, mid),
                ).fetchone()
                if row:
                    local_info = json.loads(row[0])
                    for key in ("role", "parentID"):
                        if str(local_info.get(key) or "") != str(info.get(key) or ""):
                            return False
                for part in item.get("parts") or []:
                    pid = str(part.get("id") or "")
                    if not pid:
                        return False
                    part_row = conn.execute(
                        "SELECT message_id, data FROM part WHERE session_id=? AND id=?",
                        (session_id, pid),
                    ).fetchone()
                    if not part_row:
                        continue
                    if str(part_row[0]) != mid:
                        return False
                    local_part = json.loads(part_row[1])
                    for key in ("type", "tool", "callID"):
                        if str(local_part.get(key) or "") != str(part.get(key) or ""):
                            return False
        finally:
            conn.close()
    except (OSError, sqlite3.Error, TypeError, json.JSONDecodeError):
        return False
    return True


def backup_local_snapshot(session_id: str, *, runner=subprocess.run) -> Path:
    """Export the current local revision before replacing it with a newer one."""
    root = Path(os.environ.get("DUAL_TMUX_HOME", Path.home() / ".dual-tmux"))
    dest_dir = root / "backups" / "opencode"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
    dest = dest_dir / f"{session_id}-{stamp}.json"
    import tempfile

    fd, tmp = tempfile.mkstemp(prefix=f".{session_id}.", suffix=".json", dir=dest_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            result = runner(
                [oc_bin(), "export", session_id],
                stdout=fh,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
                check=False,
            )
        if result.returncode != 0:
            err = (result.stderr or "").strip().splitlines()
            raise SystemExit(
                f"[err] backup export {session_id}: {err[-1] if err else 'failed'}"
            )
        if not _snapshot_revision(Path(tmp), session_id):
            raise SystemExit(f"[err] backup export {session_id}: invalid snapshot")
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dest


def export_snapshot(
    info: dict,
    tenant: str,
    root: Path | None = None,
    *,
    runner=subprocess.run,
) -> Path | None:
    """Export a live local session into the persist tree when it changed.

    Only the session's owning Client can export (its sqlite holds the data);
    callers must already hold the tunnel lock. Returns the snapshot path only
    when the snapshot was (re)written; None when fresh or nothing local to
    export. Raises SystemExit when the export itself fails.
    """
    sid = (info.get("session_id") or "").strip()
    if not sid or not tenant:
        return None
    if (info.get("tool") or "opencode") != "opencode":
        return None
    if not by_id(sid):
        return None
    slug = (info.get("slug") or "").strip() or sid
    dest_dir = (root or persist_root()) / tenant
    dest = dest_dir / f"{slug}.json"
    updated = session_updated_ms(sid)
    if updated and dest.is_file() and dest.stat().st_mtime >= updated / 1000:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    import tempfile

    fd, tmp = tempfile.mkstemp(prefix=f".{slug}.", suffix=".json", dir=str(dest_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            result = runner(
                [oc_bin(), "export", sid],
                stdout=fh,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
                check=False,
            )
        if result.returncode != 0:
            err = (result.stderr or "").strip().splitlines()
            raise SystemExit(
                f"[err] opencode export {sid}: {err[-1] if err else 'failed'}"
            )
        with open(tmp, encoding="utf-8") as fh:
            payload = json.load(fh)
        if (payload.get("info") or {}).get("id") != sid:
            raise SystemExit(f"[err] opencode export {sid}: snapshot id mismatch")
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return dest


def _tick_snapshots(
    info: dict, source: str | None, role: str, sid: str, local: object
) -> tuple[SnapshotRevision, ...]:
    """Pick one MACHINE snapshot from ticks, never union all tm_* trees."""
    if source:
        snapshots = resolve_snapshots(info, source=source)
        if snapshots:
            return snapshots
        local_tenant = persist_tenant()
        if source == local_tenant and local:
            return ()
        slug = info.get("slug") or "—"
        raise SystemExit(
            f"[err] {role} session {sid} ({slug}) has no persist JSON under "
            f"{persist_root()}/{source}/. Pull persist, then dt resume."
        )
    newest = resolve_snapshot(info)
    return (newest,) if newest else ()


def ensure_local(
    info: dict,
    *,
    importer=None,
    backupper=None,
    prepare_replace=None,
    role: str = "trigger",
    dry_run: bool = False,
    pick: str = "union",
    source: str | None = None,
) -> bool:
    """Converge a local OpenCode session to the union of persisted revisions.

    Returns True if import ran. Existing rows are preserved; compatible IDs
    found only on another Client are imported after one local backup.
    pick='tick' uses one MACHINE chosen by fingerprint ticks instead of union.
    """
    sid = (info.get("session_id") or "").strip()
    if not sid:
        return False
    local = by_id(sid)
    snapshots = (
        _tick_snapshots(info, source, role, sid, local)
        if pick == "tick"
        else resolve_snapshots(info)
    )
    if not snapshots:
        if local:
            return False
        slug = info.get("slug") or "—"
        raise SystemExit(
            f"[err] {role} session {sid} ({slug}) not in local sqlite and no persist JSON "
            f"under {persist_root()}/tm_*/. Pull persist, then dt resume."
        )
    local_tail = local_tail_message_id(sid) if local else ""
    local_ids = _local_message_ids(sid) if local else frozenset()
    pending = (
        [snap for snap in snapshots if snap.message_ids - local_ids]
        if local
        else list(snapshots)
    )
    if not pending:
        return False
    if local:
        incompatible = next(
            (
                snap
                for snap in pending
                if not _snapshot_identity_compatible_with_local(sid, snap.path)
            ),
            None,
        )
        if incompatible:
            raise SystemExit(
                f"[err] snapshot_conflict: local {role} {sid} and "
                f"{incompatible.path} "
                "reuse a message or part ID with incompatible graph identity"
            )

    if dry_run:
        return True

    if prepare_replace:
        prepare_replace()
    backup = None
    if local:
        backup = (backupper or backup_local_snapshot)(sid)
    for snapshot in pending:
        (importer or import_snapshot)(snapshot.path)
        if not by_id(sid):
            raise SystemExit(
                f"[err] imported {snapshot.path.name} but session {sid} still missing"
            )
        if snapshot.tail_id and not local_has_message(sid, snapshot.tail_id):
            recovery = f"; backup: {backup}" if backup else ""
            raise SystemExit(
                f"[err] imported {snapshot.path.name} but tail verification failed"
                f"{recovery}"
            )
    if local_tail and not local_has_message(sid, local_tail):
        recovery = f"; backup: {backup}" if backup else ""
        raise SystemExit(
            f"[err] imported {snapshot.path.name} but local-tail preservation failed"
            f"{recovery}"
        )
    return True


def preflight_local(
    info: dict,
    *,
    role: str = "trigger",
    pick: str = "union",
    source: str | None = None,
) -> None:
    """Validate OpenCode snapshot convergence without changing panes or data."""
    ensure_local(info, role=role, dry_run=True, pick=pick, source=source)
