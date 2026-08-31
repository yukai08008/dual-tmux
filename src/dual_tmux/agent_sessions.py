"""Conservative native session discovery for Codex and Claude Code."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .agentclient import normalize_name

Runner = Callable[..., subprocess.CompletedProcess]
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
SESSION_START_WINDOW_MS = 60_000


@dataclass(frozen=True)
class AgentSession:
    session_id: str
    directory: str = ""
    title: str = ""
    model: str = ""
    agent: str = ""
    slug: str = ""
    tool: str = ""
    created_ms: int = 0


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command or "")
    except ValueError:
        return (command or "").split()


def explicit_session_id(tool: str, commands: list[str]) -> str:
    """Extract only a session id explicitly present in a live Agent argv."""
    tool = normalize_name(tool)
    for command in commands:
        tokens = _tokens(command)
        if tool == "codex":
            for index, token in enumerate(tokens):
                if token == "resume" and index + 1 < len(tokens):
                    candidate = tokens[index + 1]
                    if UUID_RE.fullmatch(candidate):
                        return candidate
        elif tool == "claude":
            for index, token in enumerate(tokens):
                if token in {"--resume", "-r", "--session-id"} and index + 1 < len(
                    tokens
                ):
                    candidate = tokens[index + 1]
                    if UUID_RE.fullmatch(candidate):
                        return candidate
                if token.startswith(("--resume=", "--session-id=")):
                    candidate = token.partition("=")[2]
                    if UUID_RE.fullmatch(candidate):
                        return candidate
    return ""


def _epoch_ms(raw: str) -> int:
    value = (raw or "").strip().replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def _elapsed_seconds(raw: str) -> int:
    value = (raw or "").strip()
    days = 0
    if "-" in value:
        day, _, value = value.partition("-")
        days = int(day) if day.isdigit() else 0
    parts = [int(part) for part in value.split(":") if part.isdigit()]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = 0, *parts
    else:
        return 0
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def agent_process(
    pid: str, tool: str, *, runner: Runner = subprocess.run
) -> tuple[str, int]:
    """Return the matching descendant command and its approximate start epoch."""
    queue = [pid]
    seen: set[str] = set()
    tool = normalize_name(tool)
    while queue and len(seen) < 48:
        current = queue.pop(0)
        if not current or current in seen:
            continue
        seen.add(current)
        result = runner(
            ["ps", "-p", current, "-o", "command=", "-o", "etime="],
            capture_output=True,
            text=True,
            check=False,
        )
        line = (result.stdout or "").strip()
        command, _, elapsed = line.rpartition(" ")
        if tool and any(
            normalize_name(token) == tool for token in _tokens(command)[:4]
        ):
            return command, int((time.time() - _elapsed_seconds(elapsed)) * 1000)
        children = runner(
            ["pgrep", "-P", current], capture_output=True, text=True, check=False
        )
        queue.extend(
            line.strip()
            for line in (children.stdout or "").splitlines()
            if line.strip()
        )
    return "", 0


def _read_first_objects(path: Path, limit: int = 24) -> list[dict]:
    rows: list[dict] = []
    try:
        with path.open(errors="replace") as handle:
            for _ in range(limit):
                line = handle.readline()
                if not line:
                    break
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except OSError:
        pass
    return rows


def _codex_record(path: Path) -> AgentSession | None:
    for row in _read_first_objects(path):
        if row.get("type") != "session_meta":
            continue
        payload = row.get("payload") or {}
        source = payload.get("source")
        originator = payload.get("originator")
        if (
            not isinstance(source, str) or source not in {"cli", "exec"}
        ) and originator not in {
            "codex-tui",
            "codex-cli",
        }:
            return None
        sid = payload.get("session_id") or payload.get("id") or ""
        if not sid:
            return None
        return AgentSession(
            sid,
            payload.get("cwd") or "",
            payload.get("title") or "",
            payload.get("model") or "",
            tool="codex",
        )
    return None


def _claude_record(path: Path) -> AgentSession | None:
    sid = ""
    directory = ""
    created = ""
    for row in _read_first_objects(path):
        sid = sid or row.get("sessionId") or ""
        if row.get("type") == "user":
            directory = row.get("cwd") or ""
            created = row.get("timestamp") or ""
            if sid and directory:
                break
    if not sid:
        sid = path.stem
    if not sid or not directory:
        return None
    return AgentSession(sid, directory, tool="claude", created_ms=_epoch_ms(created))


def _created_ms(path: Path, session: AgentSession) -> int:
    if session.tool == "codex":
        for row in _read_first_objects(path, 4):
            if row.get("type") == "session_meta":
                payload = row.get("payload") or {}
                return _epoch_ms(payload.get("timestamp") or row.get("timestamp") or "")
    return session.created_ms or int(path.stat().st_mtime * 1000)


def _roots(tool: str, home: Path | None = None) -> list[Path]:
    base = home or Path.home()
    if tool == "codex":
        codex_home = (
            base / ".codex"
            if home is not None
            else Path(os.environ.get("CODEX_HOME", base / ".codex")).expanduser()
        )
        return [codex_home / "sessions"]
    if tool == "claude":
        return [base / ".claude" / "projects"]
    return []


def discover_local(
    tool: str,
    *,
    pid: str = "",
    commands: list[str] | None = None,
    cwd: str = "",
    home: Path | None = None,
    runner: Runner = subprocess.run,
) -> AgentSession | None:
    tool = normalize_name(tool)
    if tool not in {"codex", "claude"}:
        return None
    process_command, started_ms = (
        agent_process(pid, tool, runner=runner) if pid else ("", 0)
    )
    live_commands = [process_command, *(commands or [])]
    sid = explicit_session_id(tool, live_commands)
    parser = _codex_record if tool == "codex" else _claude_record
    records: list[tuple[Path, AgentSession, int]] = []
    for root in _roots(tool, home):
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            record = parser(path)
            if record:
                records.append((path, record, _created_ms(path, record)))
    if sid:
        for _path, record, _created in records:
            if record.session_id == sid:
                return record
        return AgentSession(sid, cwd, tool=tool)
    if not process_command or not cwd or not started_ms:
        return None
    candidates = [
        record
        for _path, record, created in records
        if Path(record.directory).expanduser() == Path(cwd).expanduser()
        and created >= started_ms - 5000
        and created <= started_ms + SESSION_START_WINDOW_MS
    ]
    return candidates[0] if len(candidates) == 1 else None


_REMOTE_CODE = r"""import glob,json,os,shlex,sys,time
tool=sys.argv[1]; expected=os.path.realpath(sys.argv[2]) if len(sys.argv)>2 and sys.argv[2] else ''; import re
uuid_re=re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
def norm(x):
 x=os.path.basename(x).lower()
 return {'codex-cli':'codex','claude-code':'claude'}.get(x,x)
def explicit(args):
 if tool=='codex':
  for i,x in enumerate(args):
   if x=='resume' and i+1<len(args) and uuid_re.fullmatch(args[i+1]): return args[i+1]
 if tool=='claude':
  for i,x in enumerate(args):
   if x in ('--resume','-r','--session-id') and i+1<len(args) and uuid_re.fullmatch(args[i+1]): return args[i+1]
   if x.startswith('--resume=') or x.startswith('--session-id='):
    value=x.split('=',1)[1]
    if uuid_re.fullmatch(value): return value
 return ''
found=[]
for raw in glob.glob('/proc/[0-9]*/cmdline'):
 try:
  pid=int(raw.split('/')[2]); args=[x.decode('utf-8','replace') for x in open(raw,'rb').read().split(b'\0') if x]
  if not any(norm(x)==tool for x in args[:4]): continue
  cwd=os.path.realpath('/proc/%s/cwd'%pid); sid=explicit(args)
  stat=open('/proc/%s/stat'%pid).read().split(); ticks=os.sysconf(os.sysconf_names['SC_CLK_TCK']); uptime=float(open('/proc/uptime').read().split()[0]); started=int((time.time()-(uptime-float(stat[21])/ticks))*1000)
  found.append((pid,sid,cwd,started))
 except (OSError,ValueError,IndexError): pass
if expected: found=[x for x in found if x[2]==expected]
if len(found)!=1: raise SystemExit(1)
pid,sid,cwd,started=found[0]
records=[]
patterns=[os.path.expanduser('~/.codex/sessions/**/*.jsonl')] if tool=='codex' else [os.path.expanduser('~/.claude/projects/**/*.jsonl')]
for pattern in patterns:
 for path in glob.glob(pattern,recursive=True):
  try:
   rows=[]
   with open(path,errors='replace') as f:
    for _ in range(24):
     line=f.readline()
     if not line: break
     try: rows.append(json.loads(line))
     except json.JSONDecodeError: pass
   if tool=='codex':
    row=next((x for x in rows if x.get('type')=='session_meta'),None); p=(row or {}).get('payload') or {}
    if p.get('source') not in ('cli','exec') and p.get('originator') not in ('codex-tui','codex-cli'): continue
    rid=p.get('session_id') or p.get('id') or ''; rcwd=p.get('cwd') or ''; stamp=p.get('timestamp') or (row or {}).get('timestamp') or ''
   else:
    row=next((x for x in rows if x.get('type')=='user' and x.get('cwd')),None); rid=next((x.get('sessionId') for x in rows if x.get('sessionId')),os.path.basename(path)[:-6]); rcwd=(row or {}).get('cwd') or ''; stamp=(row or {}).get('timestamp') or ''
   try: created=int(__import__('datetime').datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()*1000)
   except (ValueError,TypeError): created=int(os.path.getmtime(path)*1000)
   if rid: records.append((rid,rcwd,created))
  except OSError: pass
if sid:
 match=next((x for x in records if x[0]==sid),(sid,cwd,started)); print(json.dumps({'session_id':match[0],'directory':match[1],'tool':tool})); raise SystemExit(0)
candidates=[x for x in records if os.path.realpath(x[1])==cwd and started-5000<=x[2]<=started+60000]
if len(candidates)!=1: raise SystemExit(1)
print(json.dumps({'session_id':candidates[0][0],'directory':candidates[0][1],'tool':tool}))
"""


def discover_remote(
    tool: str,
    ssh_argv: list[str],
    *,
    container: str = "",
    cwd: str = "",
    runner: Runner = subprocess.run,
) -> AgentSession | None:
    tool = normalize_name(tool)
    if tool not in {"codex", "claude"}:
        return None
    command = (
        f"python3 -c {shlex.quote(_REMOTE_CODE)} {shlex.quote(tool)} {shlex.quote(cwd)}"
    )
    if container:
        command = f"docker exec {shlex.quote(container)} sh -lc {shlex.quote(command)}"
    result = runner([*ssh_argv, command], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    try:
        value = json.loads((result.stdout or "").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return None
    sid = value.get("session_id") or ""
    return AgentSession(sid, value.get("directory") or "", tool=tool) if sid else None


def start_command(tool: str, model: str = "") -> str:
    tool = normalize_name(tool)
    if tool == "codex":
        return "codex" + (f" --model {shlex.quote(model)}" if model else "")
    if tool == "claude":
        return "claude" + (f" --model {shlex.quote(model)}" if model else "")
    raise ValueError(f"unsupported native session tool: {tool or 'unknown'}")


def resume_command(tool: str, session_id: str) -> str:
    tool = normalize_name(tool)
    sid = shlex.quote((session_id or "").strip())
    if not sid:
        raise ValueError("session id is required")
    if tool == "codex":
        return f"codex resume {sid}"
    if tool == "claude":
        return f"claude --resume {sid}"
    raise ValueError(f"unsupported native session tool: {tool or 'unknown'}")


def session_exists(tool: str, session_id: str, *, home: Path | None = None) -> bool:
    tool = normalize_name(tool)
    sid = (session_id or "").strip()
    if tool not in {"codex", "claude"} or not UUID_RE.fullmatch(sid):
        return False
    parser = _codex_record if tool == "codex" else _claude_record
    for root in _roots(tool, home):
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            record = parser(path)
            if record and record.session_id == sid:
                return True
    return False


def remote_session_probe_script(tool: str, session_id: str) -> str:
    """Return a read-only Python probe suitable for an SSH/container shell."""
    tool = normalize_name(tool)
    sid = (session_id or "").strip()
    if tool not in {"codex", "claude"} or not UUID_RE.fullmatch(sid):
        return "false"
    if tool == "codex":
        patterns = "[os.path.expanduser('~/.codex/sessions/**/*.jsonl')]"
        expression = "p.get('session_id')==sid or p.get('id')==sid"
    else:
        patterns = "[os.path.expanduser('~/.claude/projects/**/*.jsonl')]"
        expression = "row.get('sessionId')==sid"
    code = (
        "import glob,json,os,sys; sid=sys.argv[1]; ok=False; "
        f"patterns={patterns}; "
        "files=[p for pattern in patterns for p in glob.glob(pattern,recursive=True)]; "
        "\nfor path in files:\n"
        " try:\n"
        "  with open(path,errors='replace') as f:\n"
        "   for _ in range(24):\n"
        "    line=f.readline()\n"
        "    if not line: break\n"
        "    try: row=json.loads(line)\n"
        "    except json.JSONDecodeError: continue\n"
        "    p=row.get('payload') or {}\n"
        f"    if {expression}: ok=True; break\n"
        "  if ok: break\n"
        " except OSError: pass\n"
        "raise SystemExit(0 if ok else 1)"
    )
    return f"python3 -c {shlex.quote(code)} {shlex.quote(sid)}"
