from __future__ import annotations

import errno
import html
import json
import os
import re
import threading
import time
import webbrowser
import zipfile
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import oc as oc_ops
from . import skillmgr
from . import tmux as tmux_ops
from .paneparse import parse_pane, parser_id_for_side
from .config import load_config
from .control import ControlError, get_control_service
from .paths import home_dir
from .recovery import read_state as read_health_state
from .store import find_dt, iter_dt_files, load, normalize_dt

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
_RESUME_LOCK = threading.Lock()
_WEB_STATE_LOCK = threading.Lock()


_CLIENT_DISCONNECT_ERRNOS = {
    errno.EBADF,
    errno.EPIPE,
    errno.ECONNABORTED,
    errno.ECONNRESET,
    errno.ENOTCONN,
}


def _is_client_disconnect(exc: BaseException | None) -> bool:
    """Recognize socket failures caused by a browser closing its request."""
    return isinstance(
        exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)
    ) or (isinstance(exc, OSError) and exc.errno in _CLIENT_DISCONNECT_ERRNOS)


def _opencode_auto(text: str) -> bool | None:
    """Return the input mode without mistaking a running status for manual mode."""
    matches = list(
        re.finditer(r"\bBuild(?P<auto>\s+auto)?\s*[·•][^\n]*", text or "", re.IGNORECASE)
    )
    running_at = (text or "").lower().rfind("esc interrupt")
    if running_at >= 0:
        before = [match for match in matches if match.start() < running_at]
        # The status immediately before `esc interrupt` describes the running
        # request and omits `auto`; the preceding prompt describes input mode.
        matches = before[:-1] if before else []
    return bool(matches[-1].group("auto")) if matches else None


def _web_state_path() -> Path:
    return home_dir() / "web-state.json"


def _clean_web_state(data: object) -> dict:
    src = data if isinstance(data, dict) else {}
    history_src = src.get("history") if isinstance(src.get("history"), dict) else {}
    history: dict[str, dict] = {}
    for name, raw in list(history_src.items())[:50]:
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 160
            or not isinstance(raw, dict)
        ):
            continue
        thread = []
        for item in (raw.get("thread") if isinstance(raw.get("thread"), list) else [])[
            -60:
        ]:
            if not isinstance(item, dict):
                continue
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            thread.append(
                {
                    "kind": str(item.get("kind") or "ans")[:16],
                    "text": str(item.get("text") or "")[:8000],
                    "extra": {
                        str(k)[:32]: str(v)[:300] for k, v in list(extra.items())[:8]
                    },
                }
            )
        log = []
        for item in (raw.get("log") if isinstance(raw.get("log"), list) else [])[-100:]:
            if isinstance(item, dict):
                log.append(
                    {
                        "kind": str(item.get("kind") or "idle")[:16],
                        "text": str(item.get("text") or "")[:1000],
                    }
                )
        try:
            visits = int(raw.get("visits") or 0)
        except (TypeError, ValueError):
            visits = 0
        history[name] = {
            "name": name,
            "firstVisitedAt": str(raw.get("firstVisitedAt") or "")[:40],
            "lastVisitedAt": str(raw.get("lastVisitedAt") or "")[:40],
            "visits": max(0, min(visits, 1_000_000)),
            "finalOp": str(raw.get("finalOp") or "gray")[:12],
            "finalRun": str(raw.get("finalRun") or "gray")[:12],
            "thread": thread,
            "log": log,
        }
    open_tabs = []
    for name in src.get("open_tabs") if isinstance(src.get("open_tabs"), list) else []:
        if isinstance(name, str) and name in history and name not in open_tabs:
            open_tabs.append(name)
        if len(open_tabs) >= 20:
            break
    active = str(src.get("active") or "")
    return {
        "version": 1,
        "open_tabs": open_tabs,
        "active": active if active in open_tabs else "",
        "history": history,
    }


def _load_web_state() -> dict:
    path = _web_state_path()
    if not path.is_file():
        return _clean_web_state({})
    try:
        return _clean_web_state(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return _clean_web_state({})


def _save_web_state(data: object) -> dict:
    cleaned = _clean_web_state(data)
    path = _web_state_path()
    with _WEB_STATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    return cleaned


def _multipart(raw: bytes, content_type: str) -> tuple[dict[str, str], list[bytes]]:
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + content_type.encode("ascii", "replace")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + raw
    )
    fields: dict[str, str] = {}
    files: list[bytes] = []
    if not message.is_multipart():
        raise SystemExit("[err] invalid upload")
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition") or ""
        payload = part.get_payload(decode=True) or b""
        if name == "files":
            files.append(payload)
        else:
            fields[name] = payload.decode("utf-8", "replace")
    return fields, files


def _tunnels() -> list[dict]:
    rows = []
    for path in iter_dt_files():
        data = load(path)
        op = data.get("op") or ""
        run = data.get("run") or ""
        op_info = tmux_ops.pane_info(op) if op else {}
        run_info = tmux_ops.pane_info(run) if run else {}
        rows.append(
            {
                "name": data.get("name") or path.stem,
                "dst": oc_ops.is_dst(data),
                "op": op,
                "run": run,
                "op_live": bool(op) and tmux_ops.has_session(op),
                "run_live": bool(run) and tmux_ops.has_session(run),
                "op_cmd": op_info.get("cmd") or "",
                "run_cmd": run_info.get("cmd") or "",
                "trigger": (data.get("trigger") or {}).get("slug") or "",
                "bullet": (data.get("bullet") or {}).get("slug") or "",
                "trigger_model": (data.get("trigger") or {}).get("model") or "",
                "bullet_model": (data.get("bullet") or {}).get("model") or "",
                "trigger_tool": (data.get("trigger") or {}).get("tool") or "opencode",
                "bullet_tool": (data.get("bullet") or {}).get("tool") or "opencode",
                "trigger_client": (data.get("trigger") or {}).get("agent_client") or {},
                "bullet_client": (data.get("bullet") or {}).get("agent_client") or {},
                "auto_recover": bool(data.get("auto_recover")),
                "health": read_health_state(data.get("name") or path.stem),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def _pane_name(data: dict, side: str) -> str:
    if side == "op":
        return data.get("op") or ""
    return data.get("run") or ""


def _resume_tunnel(name: str) -> dict:
    """Resume an offline DST for the web UI without attaching a terminal."""
    with _RESUME_LOCK:
        data = load(find_dt(name))
        if not oc_ops.is_dst(data):
            raise SystemExit("[err] automatic resume requires a DST")
        op = data.get("op") or ""
        run = data.get("run") or ""
        needed = not (
            op and run and tmux_ops.has_session(op) and tmux_ops.has_session(run)
        )
        if needed:
            # Keep this small seam patchable for local Web tests; the CLI wrapper
            # delegates to the same ControlService used by the HTTP handlers.
            from .cli import apply_resume

            data = apply_resume(name, force=False)
            op = data.get("op") or ""
            run = data.get("run") or ""
        return {
            "ok": True,
            "resumed": needed,
            "op_live": bool(op) and tmux_ops.has_session(op),
            "run_live": bool(run) and tmux_ops.has_session(run),
        }


def _switch_trigger_auto(name: str) -> dict:
    """Restart a tunnel's bound trigger session in OpenCode auto mode."""
    with _RESUME_LOCK:
        data = load(find_dt(name))
        op = data.get("op") or ""
        trigger = data.get("trigger") or {}
        if not op or not tmux_ops.has_session(op):
            raise SystemExit("[err] trigger pane is offline")
        if (trigger.get("tool") or "opencode") != "opencode":
            raise SystemExit("[err] trigger is not OpenCode")
        if not trigger.get("session_id"):
            raise SystemExit(
                "[err] trigger has no frozen session id; run dt freeze first"
            )
        if _opencode_auto(_capture(op)):
            return {"ok": True, "changed": False, "auto": True, "pane": op}
        if tmux_ops.pane_command(op) == "opencode" and not tmux_ops.quit_opencode(op):
            raise SystemExit("[err] failed to stop current trigger OpenCode")
        tmux_ops.start_opencode(op, oc_ops.resume_cmd(trigger))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if _opencode_auto(_capture(op)):
                return {"ok": True, "changed": True, "auto": True, "pane": op}
            if not tmux_ops.has_session(op):
                break
            time.sleep(0.4)
        raise SystemExit(
            "[err] trigger auto mode did not become ready within 20 seconds"
        )


def _mtime_iso(path: Path) -> str:
    if not path.is_file() and not path.is_dir():
        return ""
    try:
        ts = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _sync_info(data: dict) -> dict:
    cfg = load_config()
    source = cfg.client
    trigger = data.get("trigger") or {}
    slug = trigger.get("slug") or ""
    op = data.get("op") or ""
    run = data.get("run") or ""
    sessions = Path(
        os.environ.get("DT_SESSIONS_HOME", Path.home() / "sessions")
    ).expanduser()
    oc_json = sessions / "opencode" / source / f"{slug}.json" if slug else Path()
    tmux_dir = sessions / "tmux" / source
    last_link = tmux_dir / "last"
    oc_lock = home_dir() / "locks" / "persist-opencode"
    tmux_lock = home_dir() / "locks" / "persist-tmux"
    oc_busy = oc_lock.is_dir()
    tmux_busy = tmux_lock.is_dir()
    return {
        "source": source,
        "op": op,
        "run": run,
        "op_live": bool(op) and tmux_ops.has_session(op),
        "run_live": bool(run) and tmux_ops.has_session(run),
        "oc_slug": slug,
        "oc_file": str(oc_json) if slug else "",
        "oc_mtime": _mtime_iso(oc_json) if slug else "",
        "tmux_last": _mtime_iso(last_link),
        "tmux_dir": str(tmux_dir),
        "oc_busy": oc_busy,
        "tmux_busy": tmux_busy,
        "busy": oc_busy or tmux_busy,
    }


def _capture(name: str) -> str:
    if not name:
        return "(no pane)"
    if not tmux_ops.has_session(name):
        return f"(tmux {name} not running)"
    return tmux_ops.capture_pane(name, -500) or "(empty pane)"


def _shell(nav: str, body: str, title: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%232563eb'/%3E%3Cpath d='M15 18h34v8H36v24h-8V26H15z' fill='white'/%3E%3C/svg%3E">
<style>
:root {{ --bg:#f4f6f9; --side:#1f2a37; --side2:#16202c; --acc:#2563eb; --line:#e5e7eb; --text:#111827; --muted:#6b7280; --ok:#059669; --card:#fff; }}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; height:100%; background:var(--bg); color:var(--text); font:13px/1.45 ui-sans-serif,system-ui,sans-serif; }}
.app {{ display:flex; height:100%; }}
.side {{ width:200px; background:var(--side); color:#e5e7eb; display:flex; flex-direction:column; }}
.brand {{ padding:16px; font-weight:700; border-bottom:1px solid #2c3a4d; }}
.brand span {{ display:block; font-weight:400; color:#9ca3af; font-size:11px; margin-top:2px; }}
.nav {{ padding:8px; display:flex; flex-direction:column; gap:4px; }}
.nav a {{ color:#d1d5db; text-decoration:none; padding:10px 12px; border-radius:6px; }}
.nav a:hover {{ background:#2c3a4d; color:#fff; }}
.nav a.active {{ background:var(--acc); color:#fff; }}
.main {{ flex:1; min-width:0; display:flex; flex-direction:column; overflow:auto; }}
.top {{ padding:14px 20px; background:var(--card); border-bottom:1px solid var(--line); }}
.top h1 {{ margin:0; font-size:16px; }}
.top p {{ margin:4px 0 0; color:var(--muted); }}
.content {{ padding:16px 20px; flex:1; display:flex; flex-direction:column; gap:12px; min-height:0; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }}
.stat b {{ display:block; font-size:20px; }}
.stat span {{ color:var(--muted); font-size:12px; }}
label {{ display:block; font-weight:600; margin-bottom:6px; }}
input[type=search], textarea {{ width:100%; border:1px solid var(--line); border-radius:6px; padding:8px 10px; font:13px ui-sans-serif,system-ui; }}
textarea {{ min-height:16em; height:16em; font:13px ui-monospace,Menlo,monospace; resize:vertical; }}
button {{ background:var(--acc); color:#fff; border:0; border-radius:6px; padding:8px 14px; font-weight:600; cursor:pointer; }}
.pick {{ position:relative; }}
.hits {{ position:absolute; left:0; right:0; top:100%; background:#fff; border:1px solid var(--line); border-radius:6px; max-height:240px; overflow:auto; z-index:5; display:none; }}
.hits a {{ display:block; padding:8px 10px; text-decoration:none; color:var(--text); }}
.hits a:hover, .hits a.active {{ background:#eff6ff; }}
.hits .sub {{ color:var(--muted); font-size:11px; }}
.meta {{ color:var(--muted); font-size:12px; }}
.log {{ height:180px; overflow:auto; background:#f8fafc; border:1px solid var(--line); border-radius:6px; padding:6px 8px; font:12px/1.45 ui-sans-serif,system-ui; }}
.log .row {{ display:flex; gap:8px; padding:3px 0; border-bottom:1px solid #eef2f7; }}
.log .row:last-child {{ border-bottom:0; }}
.log .tag {{ flex:0 0 64px; font-size:10px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; color:#fff; background:#6b7280; border-radius:4px; text-align:center; padding:2px 0; height:fit-content; }}
.log .tag.send {{ background:#2563eb; }}
.log .tag.poll {{ background:#0891b2; }}
.log .tag.idle {{ background:#6b7280; }}
.log .tag.done {{ background:#059669; }}
.log .tag.err {{ background:#dc2626; }}
.log .tag.pick {{ background:#7c3aed; }}
.log .msg {{ color:#374151; flex:1; }}
.out {{ margin:0; height:380px; overflow:auto; background:#0b1220; color:#dbeafe; padding:12px 14px; border-radius:6px; font:13px/1.5 ui-monospace,Menlo,monospace; white-space:pre-wrap; word-break:break-word; }}
h2 {{ margin:0 0 8px; font-size:13px; }}
.h2row {{ display:flex; align-items:center; gap:12px; margin-bottom:8px; }}
.pollhead {{ display:flex; align-items:center; gap:8px; }}
.pollhead .spin {{ width:10px; height:10px; border-radius:50%; background:#9ca3af; }}
.pollhead.busy .spin {{ background:#f59e0b; animation:blink 0.9s ease-in-out infinite; }}
.bubble .meta {{ font-size:11px; color:#6b7280; margin-top:6px; }}
.h2row h2 {{ margin:0; }}
.lamps {{ display:flex; gap:10px; }}
.lamp-wrap {{ display:flex; align-items:center; gap:5px; font-size:12px; color:var(--muted); }}
.lamp {{ width:12px; height:12px; border-radius:50%; background:#9ca3af; box-shadow:0 0 0 2px #e5e7eb; }}
.lamp.gray {{ background:#9ca3af; box-shadow:0 0 0 2px #e5e7eb; }}
.lamp.red {{ background:#dc2626; box-shadow:0 0 0 2px #fecaca; }}
.lamp.green {{ background:#059669; box-shadow:0 0 0 2px #a7f3d0; }}
.lamp.yellow {{ background:#f59e0b; box-shadow:0 0 0 2px #fde68a; animation:blink 0.9s ease-in-out infinite; }}
@keyframes blink {{ 50% {{ opacity:0.3; }} }}
.log.busy {{ border-color:#f59e0b; background:#fffbeb; }}
.log.idle {{ border-color:var(--line); background:#f3f4f6; }}
.thread {{ height:240px; overflow:auto; background:#f8fafc; border:1px solid var(--line); border-radius:6px; padding:8px; display:flex; flex-direction:column; gap:8px; }}
.bubble {{ border-radius:8px; padding:8px 10px; max-width:92%; }}
.bubble .who {{ font-size:10px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; margin-bottom:4px; }}
.bubble .body {{ white-space:pre-wrap; word-break:break-word; font:13px/1.45 ui-sans-serif,system-ui; }}
.bubble.ask {{ align-self:flex-end; background:#dbeafe; color:#1e3a8a; }}
.bubble.ask .who {{ color:#1d4ed8; }}
.bubble.ans {{ align-self:flex-start; background:#ecfdf5; color:#065f46; }}
.bubble.ans .who {{ color:#047857; }}
.bubble.fail {{ align-self:flex-start; background:#fef2f2; color:#991b1b; }}
.bubble.fail .who {{ color:#dc2626; }}
.btabs {{ display:flex; align-items:flex-end; gap:0; border-bottom:1px solid var(--line); overflow-x:auto; }}
.btab {{ display:flex; align-items:center; gap:8px; padding:8px 10px 8px 12px; border:1px solid var(--line); border-bottom:none; border-radius:8px 8px 0 0; background:#e5e7eb; color:#4b5563; cursor:pointer; margin-right:4px; white-space:nowrap; }}
.btab.active {{ background:#fff; color:var(--text); font-weight:600; }}
.btab .dot {{ width:8px; height:8px; border-radius:50%; background:#9ca3af; flex:0 0 auto; }}
.btab.gray .dot {{ background:#9ca3af; }}
.btab.red .dot {{ background:#dc2626; }}
.btab.green .dot {{ background:#059669; }}
.btab.yellow .dot {{ background:#f59e0b; animation:blink 0.9s ease-in-out infinite; }}
.btab.gray {{ background:#e5e7eb; }}
.btab.red {{ background:#fee2e2; }}
.btab.green {{ background:#d1fae5; }}
.btab.yellow {{ background:#fef3c7; }}
.btab .x {{ border:0; background:transparent; color:#6b7280; cursor:pointer; font-size:14px; padding:0 2px; }}
.btab-add {{ border:1px dashed var(--line); background:#fff; color:var(--muted); padding:8px 12px; border-radius:8px 8px 0 0; cursor:pointer; }}
.recent {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; color:var(--muted); font-size:11px; }}
.recent button {{ background:#f3f4f6; color:#374151; border:1px solid var(--line); padding:4px 8px; font-weight:500; display:inline-flex; gap:6px; align-items:center; }}
.recent button small {{ color:var(--muted); font-weight:400; }}
.recent button:hover {{ background:#eff6ff; border-color:#93c5fd; }}
.models {{ display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin-top:10px; }}
.models label {{ margin:0; font-size:11px; color:var(--muted); }}
.models .field {{ position:relative; }}
.models input {{ width:260px; padding:6px 8px; }}
.models button {{ padding:6px 10px; }}
.models .ghost {{ background:#fff; color:var(--acc); border:1px solid var(--acc); }}
.sync {{ font:12px/1.5 ui-sans-serif,system-ui; color:#374151; }}
.sync .row {{ display:flex; gap:10px; padding:4px 0; border-bottom:1px dashed var(--line); }}
.sync .k {{ flex:0 0 88px; color:var(--muted); }}
.sync .v {{ flex:1; font-family:ui-monospace,Menlo,monospace; }}
.sync .chg {{ color:#059669; font-size:11px; }}
.syncbar {{ display:flex; gap:16px; align-items:center; flex-wrap:wrap; }}
.sess {{ display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:8px; background:#f3f4f6; border:1px solid var(--line); font-family:ui-monospace,Menlo,monospace; }}
.sess .spin {{ width:10px; height:10px; border:2px solid #e5e7eb; border-top-color:#f59e0b; border-radius:50%; }}
.sess.busy {{ background:#fffbeb; border-color:#f59e0b; color:#92400e; }}
.sess.busy .spin {{ animation:spin 0.8s linear infinite; }}
.sess.ok {{ background:#ecfdf5; border-color:#059669; color:#065f46; }}
.sess.ok .spin {{ display:none; }}
.sess.ok::before {{ content:""; width:8px; height:8px; border-radius:50%; background:#059669; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
.mhits {{ position:absolute; left:0; right:0; top:100%; background:#fff; border:1px solid var(--line); border-radius:6px; max-height:220px; overflow:auto; z-index:30; display:none; box-shadow:0 8px 20px rgba(0,0,0,.12); }}
.mhits a {{ display:block; padding:6px 8px; text-decoration:none; color:var(--text); font:12px ui-monospace,Menlo,monospace; }}
.mhits a:hover {{ background:#eff6ff; }}
.guide-table {{ width:100%; border-collapse:collapse; }}
.guide-table th,.guide-table td {{ text-align:left; vertical-align:top; padding:8px 10px; border-bottom:1px solid var(--line); }}
.guide-table th {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
.guide-table code,.cmd {{ font:12px ui-monospace,Menlo,monospace; background:#eef2ff; color:#3730a3; border-radius:4px; padding:2px 5px; }}
.cmdblock {{ margin:6px 0 0; padding:10px 12px; white-space:pre-wrap; background:#0b1220; color:#dbeafe; border-radius:6px; font:12px/1.55 ui-monospace,Menlo,monospace; }}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand">dt web<span>local admin</span></div>
    <nav class="nav">{nav}</nav>
  </aside>
  <section class="main">{body}</section>
</div>
</body>
</html>
"""


def _nav(page: str) -> str:
    dash = "active" if page == "dashboard" else ""
    tun = "active" if page == "tunnels" else ""
    sk = "active" if page == "skills" else ""
    guide = "active" if page == "guide" else ""
    memory = "active" if page == "memory" else ""
    events = "active" if page == "events" else ""
    doctor = "active" if page == "doctor" else ""
    feishu = "active" if page == "feishu" else ""
    return (
        f'<a class="{dash}" href="/">Dashboard</a>'
        f'<a class="{tun}" href="/tunnels">隧道</a>'
        f'<a class="{memory}" href="/memory">Memory</a>'
        f'<a class="{events}" href="/events">Events</a>'
        f'<a class="{doctor}" href="/doctor">Doctor</a>'
        f'<a class="{feishu}" href="/feishu">飞书</a>'
        f'<a class="{sk}" href="/skills">Skills</a>'
        f'<a class="{guide}" href="/guide">指南</a>'
    )


def feishu_page() -> str:
    body = """
    <div class="top"><h1>飞书</h1><p>扫码即用：自动创建机器人并由 dt daemon 保持长连接</p></div>
    <div class="content">
      <div class="grid">
        <div class="stat"><b id="fs-configured">—</b><span>安装状态</span></div>
        <div class="stat"><b id="fs-bound">0</b><span>已绑定 operator</span></div>
        <div class="stat"><b id="fs-ws">—</b><span>WebSocket</span></div>
      </div>
      <div class="card">
        <h2>扫码绑定</h2>
        <p>不需要 App ID、App Secret 或公网 callback。飞书确认后会自动创建 PersonalAgent，凭据只以加密形式保存在服务端。</p>
        <div class="models"><button id="fs-pair">生成 10 分钟二维码</button><button class="ghost" id="fs-unbind">解绑机器人</button></div>
        <div id="fs-pair-box" style="display:none;margin-top:12px"><img id="fs-qr" alt="飞书绑定二维码" width="260" height="260"><p><a id="fs-url" target="_blank" rel="noopener">在飞书授权页打开</a></p><p class="meta" id="fs-expiry"></p></div>
        <pre class="out" id="fs-result" style="height:180px">等待操作</pre>
      </div>
      <div class="card"><h2>已绑定身份</h2><div id="fs-bindings" class="log" style="height:220px"></div></div>
    </div>
    <script>
    const out=document.getElementById('fs-result');
    async function api(url,body){const r=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw new Error((j.error&&j.error.message)||JSON.stringify(j));return j}
    async function refresh(){try{const s=await api('/api/feishu/status');document.getElementById('fs-configured').textContent=s.installed?'ready':(s.registration_status||'idle');document.getElementById('fs-bound').textContent=(s.bindings||[]).length;document.getElementById('fs-ws').textContent=((s.daemon||{}).connector||'stopped');document.getElementById('fs-bindings').innerHTML=(s.bindings||[]).map(x=>'<div class="row"><span class="tag done">bound</span><span class="msg">'+Object.entries(x).filter(([k,v])=>v).map(([k,v])=>k+'='+v).join(' · ')+'</span></div>').join('')||'尚未绑定';if(s.registration_status==='pending'){const p=await api('/api/feishu/poll',{});if(p.status==='installed'){out.textContent='绑定成功；dt daemon 将自动启动 WebSocket。';document.getElementById('fs-pair-box').style.display='none';}}}catch(e){out.textContent=e.message}}
    document.getElementById('fs-pair').onclick=async()=>{try{const j=await api('/api/feishu/pair',{});document.getElementById('fs-pair-box').style.display='block';document.getElementById('fs-qr').src=j.qr;document.getElementById('fs-url').href=j.authorization_url;document.getElementById('fs-expiry').textContent='有效期 '+j.expires_in+' 秒';out.textContent='二维码已生成；请用飞书扫码确认，页面会自动完成安装。'}catch(e){out.textContent=e.message}};
    document.getElementById('fs-unbind').onclick=async()=>{if(!confirm('解绑飞书机器人并停止对应 WebSocket？'))return;try{out.textContent=JSON.stringify(await api('/api/feishu/unbind',{}),null,2);await refresh()}catch(e){out.textContent=e.message}};
    refresh();setInterval(refresh,3000);
    </script>"""
    return _shell(_nav("feishu"), body, "dt web · 飞书")


def memory_page() -> str:
    options = "".join(
        f'<option value="{html.escape(row["name"])}">{html.escape(row["name"])}</option>'
        for row in _tunnels()
    )
    body = f"""
    <div class="top"><h1>Memory</h1><p>共享 facts 与每个 trigger 的 notes/FTS</p></div>
    <div class="content">
      <div class="card models"><div class="field"><label>Tunnel（留空为共享 facts）</label><select id="mem-tunnel"><option value="">共享</option>{options}</select></div><button id="mem-load">刷新</button></div>
      <div class="card"><h2>Facts</h2><pre class="out" id="mem-facts" style="height:220px"></pre><form id="factf" class="models"><div class="field"><label>Key</label><input id="fact-key"></div><div class="field"><label>Value（JSON 或文本）</label><input id="fact-value"></div><button type="submit">保存 fact</button></form></div>
      <div class="card"><h2>Notes</h2><div id="notes" class="log" style="height:260px"></div><form id="notef" class="models"><div class="field"><label>标题</label><input id="note-title"></div><div class="field"><label>内容</label><input id="note-body"></div><button type="submit">新增 note</button></form></div>
    </div>
    <script>
    async function loadMem(){{const t=document.getElementById('mem-tunnel').value; const r=await fetch('/api/memory?t='+encodeURIComponent(t)); const j=await r.json(); document.getElementById('mem-facts').textContent=JSON.stringify(j.memory||{{}},null,2); document.getElementById('notes').innerHTML=(j.notes||[]).map(n=>'<div class="row"><b>'+String(n.title||n.kind||'note')+'</b><span class="msg">'+String(n.body||'')+'</span></div>').join('')||'暂无 notes';}}
    async function post(url,f){{const r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:new URLSearchParams(f)}});if(!r.ok)throw new Error(await r.text());return r.json();}}
    document.getElementById('mem-load').onclick=loadMem;
    document.getElementById('factf').onsubmit=async e=>{{e.preventDefault();await post('/api/memory/fact',{{t:document.getElementById('mem-tunnel').value,key:document.getElementById('fact-key').value,value:document.getElementById('fact-value').value}});await loadMem();}};
    document.getElementById('notef').onsubmit=async e=>{{e.preventDefault();const t=document.getElementById('mem-tunnel').value;if(!t){{alert('新增 note 需要选择 tunnel');return}}await post('/api/memory/note',{{t,title:document.getElementById('note-title').value,body:document.getElementById('note-body').value}});await loadMem();}};
    loadMem();
    </script>"""
    return _shell(_nav("memory"), body, "dt web · memory")


def events_page() -> str:
    body = """
    <div class="top"><h1>Events</h1><p>CLI/Web/恢复审计事件</p></div>
    <div class="content"><div class="card models"><div class="field"><label>Kind 前缀</label><input id="event-kind"></div><div class="field"><label>Tunnel</label><input id="event-name"></div><button id="event-load">刷新</button></div><div class="card"><pre class="out" id="event-out" style="height:70vh"></pre></div></div>
    <script>async function loadEvents(){const q=new URLSearchParams({kind:document.getElementById('event-kind').value,t:document.getElementById('event-name').value});const r=await fetch('/api/events?'+q);document.getElementById('event-out').textContent=JSON.stringify(await r.json(),null,2)}document.getElementById('event-load').onclick=loadEvents;loadEvents();</script>"""
    return _shell(_nav("events"), body, "dt web · events")


def doctor_page() -> str:
    body = """
    <div class="top"><h1>Doctor</h1><p>页面加载不执行 SSH；点击后才运行完整检查</p></div>
    <div class="content"><div class="card"><button id="doctor-run">运行 Doctor</button><p class="meta">升级、hotfix、cron 安装属于主机维护面：请使用 <code>dt upgrade</code>、<code>dt hotfix</code>、<code>dt cron --install</code>。</p></div><div class="card"><pre class="out" id="doctor-out" style="height:60vh">尚未运行</pre></div></div>
    <script>document.getElementById('doctor-run').onclick=async()=>{const r=await fetch('/api/doctor/run',{method:'POST'});document.getElementById('doctor-out').textContent=JSON.stringify(await r.json(),null,2)}</script>"""
    return _shell(_nav("doctor"), body, "dt web · doctor")


def dashboard_page() -> str:
    rows = _tunnels()
    live = sum(1 for r in rows if r["op_live"] or r["run_live"])
    dst = sum(1 for r in rows if r["dst"])
    cards = []
    for r in rows:
        live_s = "live" if (r["op_live"] or r["run_live"]) else "down"
        health_s = r["health"].get("status") or "disabled"
        kind = "DST" if r["dst"] else "DT"
        cards.append(
            f'<div class="stat"><b>{html.escape(r["name"])}</b>'
            f"<span>{kind} · {live_s} · health {html.escape(health_s)} · op {html.escape(r['op_cmd'] or '—')} · "
            f"run {html.escape(r['run_cmd'] or '—')}</span></div>"
        )
    body = f"""
    <div class="top"><h1>Dashboard</h1><p>本机隧道一览（dt ls）</p></div>
    <div class="content">
      <div class="grid">
        <div class="stat"><b>{len(rows)}</b><span>tunnels</span></div>
        <div class="stat"><b>{dst}</b><span>DST</span></div>
        <div class="stat"><b>{live}</b><span>tmux live</span></div>
      </div>
      <div class="grid">{"".join(cards) or '<div class="meta">暂无隧道</div>'}</div>
    </div>
    """
    return _shell(_nav("dashboard"), body, "dt web · dashboard")


def guide_page() -> str:
    scenarios = [
        (
            "首次配置",
            "可纯本地启动，也可立即配置同步 Hub。",
            "dt config --init --local --client tm_laptop\n"
            "# 以后接入或更换 Hub\n"
            "dt config --server myserver --user andy\n"
            "dt doctor",
        ),
        (
            "创建完整 DST",
            "一次建立 op/run tmux、两侧 Agent 并冻结绑定。",
            "dt make dst myapp --model provider/model\ndt inspect myapp\ndt web",
        ),
        (
            "分步创建",
            "先建 DT，再分别启动 trigger 与 bullet。",
            "dt new myapp\ndt enter myapp --oc\ndt work myapp --oc\ndt freeze myapp",
        ),
        (
            "日常继续工作",
            "恢复已冻结会话；Web 选择离线 DST 时也会自动 resume。",
            "dt resume myapp\ndt enter myapp\ndt work myapp",
        ),
        (
            "另一台 Client 接续",
            "拉取绑定后恢复；正常锁冲突不会强制抢占。",
            "dt pull\ndt resume myapp\n# 确认需要抢占时\ndt resume myapp --force",
        ),
        (
            "分叉独立工作",
            "复制跳板与模型，但为两侧创建新的 Agent 会话。",
            "dt branch myapp myapp-v2",
        ),
        (
            "模型与现场",
            "切换单侧模型，或重新发送远端跳转命令。",
            "dt model myapp --op provider/model\ndt model myapp --run provider/model\ndt re myapp",
        ),
        ("释放本机", "停止本机 tmux 并释放锁，远端绑定保持可恢复。", "dt drop myapp"),
    ]
    cards = "".join(
        f'<div class="card"><h2>{html.escape(title)}</h2><p class="meta">{html.escape(desc)}</p>'
        f'<pre class="cmdblock">{html.escape(commands)}</pre></div>'
        for title, desc, commands in scenarios
    )
    commands = [
        ("dt config --init --local", "只配置本机 Client，不连接 Hub"),
        ("dt config --server H --user U", "合并数据后接入或更换 Hub"),
        ("dt config --local", "最后合并后退出 Hub，保留本地数据"),
        ("dt ls", "列出 DT、DST 与两侧状态"),
        ("dt inspect <name>", "查看模型、session id、工作点和时间"),
        ("dt new <name>", "创建 op/run tmux，只得到 DT"),
        ("dt make dst <name>", "一键创建 DT、两侧 Agent 并 freeze"),
        ("dt resume <name>", "恢复已冻结 DST，不创建新的会话 ID"),
        ("dt enter / work <name>", "分别进入 trigger / bullet 一侧"),
        ("dt freeze <name>", "记录两侧 tool、model 和 session id"),
        ("dt send <name> '…'", "直接向 bullet pane 发送任务"),
        ("dt branch <src> <dest>", "创建独立的新 DST 分支"),
        ("dt push / pull", "立即同步或拉取 hub 中的隧道绑定"),
        ("dt drop <name>", "停止本机现场并释放 hub 锁"),
        ("dt doctor", "检查配置、tmux、SSH 与持久化环境"),
        ("dt log", "查看命令和 freeze 事件日志"),
        ("dt skill ls", "查看 Skill catalog 与启用状态"),
        ("dt upgrade", "升级 dual-tmux 并应用必要 hotfix"),
    ]
    rows = "".join(
        f"<tr><td><code>{html.escape(command)}</code></td><td>{html.escape(desc)}</td></tr>"
        for command, desc in commands
    )
    body = f"""
    <div class="top"><h1>使用指南</h1><p>按场景查找 dual-tmux 工作流与常用命令</p></div>
    <div class="content">
      <div class="grid">{cards}</div>
      <div class="card"><h2>命令速查</h2><table class="guide-table">
        <thead><tr><th>命令</th><th>用途</th></tr></thead><tbody>{rows}</tbody>
      </table></div>
    </div>
    """
    return _shell(_nav("guide"), body, "dt web · 使用指南")


def skills_page() -> str:
    tunnels = json.dumps([r["name"] for r in _tunnels()], ensure_ascii=False)
    body = f"""
    <div class="top"><h1>Skills</h1><p>全集 ~/.dual-tmux/skills · trigger 子集进 op_* · 可传授给 bullet</p></div>
    <div class="content">
      <div class="card">
        <h2>导入（folder / SKILL.md / zip）</h2>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <select id="pick-kind" aria-label="预览类型" style="padding:8px;border:1px solid var(--line);border-radius:6px">
            <option value="folder">文件夹</option><option value="file">SKILL.md / ZIP</option>
          </select>
          <button type="button" id="btn-preview">选择并预览</button>
          <button type="button" id="btn-import" disabled>确认导入</button>
          <input id="pick-dir" type="file" webkitdirectory multiple hidden>
          <input id="pick-file" type="file" accept=".md,.markdown,.zip,text/markdown,application/zip" hidden>
        </div>
        <div class="meta" id="prev-meta" style="margin-top:8px"></div>
        <div id="tree" style="margin-top:10px;max-height:280px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:8px;background:#fff;font:12px ui-monospace,Menlo,monospace"></div>
        <pre class="out" id="preview" style="height:320px;margin-top:10px;background:#111827">选择文件夹、SKILL.md 或 ZIP；预览不会上传，确认导入时才发送到本机 dt web</pre>
      </div>
      <div class="card">
        <h2>目录</h2>
        <div id="cat"></div>
      </div>
      <div class="card">
        <h2>使用日志</h2>
        <div id="ulog" class="log idle" style="height:160px"></div>
      </div>
    </div>
<script>
const tunnels = {tunnels};
async function jget(url) {{ const r = await fetch(url); return r.json(); }}
async function jpost(url, fields) {{
  const r = await fetch(url, {{ method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'}}, body: new URLSearchParams(fields) }});
  const t = await r.text();
  if (!r.ok) throw new Error(t);
  try {{ return JSON.parse(t); }} catch {{ return {{ok:true}}; }}
}}
function esc(s) {{ return (s||'').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]); }}
async function loadCat() {{
  const rows = await jget('/api/skills');
  const dtOpts = tunnels.map(n => '<option value="'+n+'">'+n+'</option>').join('');
  document.getElementById('cat').innerHTML = rows.map(r => `
    <div class="row" style="display:flex;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)">
      <div style="flex:1"><b>${{esc(r.name)}}</b><div class="meta">${{esc(r.description)}}</div></div>
      <label style="font-weight:400"><input type="checkbox" data-en="${{r.name}}" data-who="trigger" ${{r.trigger?'checked':''}}> trigger</label>
      <label style="font-weight:400"><input type="checkbox" data-en="${{r.name}}" data-who="bullet" ${{r.bullet?'checked':''}}> bullet</label>
      <select data-teach="${{r.name}}"><option value="">teach →</option>${{dtOpts}}</select>
      <button type="button" data-view="${{r.name}}">内容</button>
      <button type="button" data-ok="${{r.name}}">used ok</button>
      <button type="button" data-fail="${{r.name}}">used fail</button>
    </div>`).join('') || '<div class="meta">空目录</div>';
}}
async function loadLog() {{
  const rows = await jget('/api/skill-log?n=40');
  document.getElementById('ulog').innerHTML = rows.map(r =>
    '<div class="row"><span class="tag '+(r.ok?'done':'err')+'">'+(r.ok?'ok':'fail')+'</span><span class="msg">'+esc(r.ts)+' · '+esc(r.dt)+' · '+esc(r.who)+' · '+esc(r.skill)+' · '+esc(r.detail||'')+'</span></div>'
  ).join('') || '<div class="meta">暂无使用记录</div>';
}}
let selectedSource = null;
function hiddenPath(rel) {{ return (rel||'').split('/').some(part => part.startsWith('.')); }}
function renderTree(files) {{
  const el = document.getElementById('tree');
  if (!files || !files.length) {{ el.innerHTML='<div class="meta">空</div>'; return; }}
  const root={{name:'',path:'',dirs:new Map(),files:[]}};
  files.forEach((entry,index) => {{
    const parts=entry.rel.split('/'), name=parts.pop(); let node=root, path='';
    parts.forEach(part => {{
      path=path ? path+'/'+part : part;
      if (!node.dirs.has(part)) node.dirs.set(part,{{name:part,path,dirs:new Map(),files:[]}});
      node=node.dirs.get(part);
    }});
    node.files.push({{name,index,entry}});
  }});
  const selectable=selectedSource && selectedSource.kind === 'folder';
  function branch(node,depth) {{
    let out='';
    [...node.dirs.values()].sort((a,b)=>a.name.localeCompare(b.name)).forEach(dir => {{
      const descendants=files.filter(f=>f.rel.startsWith(dir.path+'/'));
      const checked=descendants.length && descendants.every(f=>f.selected !== false);
      const partial=descendants.some(f=>f.selected !== false) && !checked;
      const box=selectable ? '<input type="checkbox" data-dir="'+esc(dir.path)+'" '+(checked?'checked':'')+' data-partial="'+(partial?'1':'0')+'"> ' : '';
      out+='<details open style="margin-left:'+depth*16+'px"><summary>'+box+'<span>📁 '+esc(dir.name)+'</span></summary>'+branch(dir,depth+1)+'</details>';
    }});
    node.files.sort((a,b)=>a.name.localeCompare(b.name)).forEach(f => {{
      const box=selectable ? '<input type="checkbox" data-check="'+f.index+'" '+(f.entry.selected !== false?'checked':'')+'> ' : '';
      out+='<div class="row" style="padding:3px 0;margin-left:'+depth*16+'px">'+box+'<a href="#" data-file="'+f.index+'" style="color:#2563eb">📄 '+esc(f.name)+'</a></div>';
    }});
    return out;
  }}
  const allChecked=files.every(f=>f.selected !== false), someChecked=files.some(f=>f.selected !== false);
  const rootBox=selectable ? '<input type="checkbox" data-dir="" '+(allChecked?'checked':'')+' data-partial="'+(someChecked&&!allChecked?'1':'0')+'"> ' : '';
  el.innerHTML='<details open><summary>'+rootBox+'<b>📁 '+esc(selectedSource.name)+'</b></summary>'+branch(root,1)+'</details>';
  el.querySelectorAll('input[data-partial="1"]').forEach(cb=>cb.indeterminate=true);
}}
function zipEntries(buffer) {{
  const v = new DataView(buffer); let eocd = -1;
  for (let i=buffer.byteLength-22; i>=Math.max(0, buffer.byteLength-65557); i--) {{
    if (v.getUint32(i,true) === 0x06054b50) {{ eocd=i; break; }}
  }}
  if (eocd < 0) throw new Error('不是有效的 ZIP');
  const count=v.getUint16(eocd+10,true), decoder=new TextDecoder(), out=[];
  let p=v.getUint32(eocd+16,true);
  for (let i=0; i<count; i++) {{
    if (v.getUint32(p,true) !== 0x02014b50) throw new Error('ZIP 目录损坏');
    const method=v.getUint16(p+10,true), size=v.getUint32(p+20,true);
    const nameLen=v.getUint16(p+28,true), extraLen=v.getUint16(p+30,true), commentLen=v.getUint16(p+32,true);
    const rel=decoder.decode(new Uint8Array(buffer,p+46,nameLen));
    if (!rel.endsWith('/') && !hiddenPath(rel)) out.push({{rel,method,size,offset:v.getUint32(p+42,true)}});
    p += 46+nameLen+extraLen+commentLen;
  }}
  return out;
}}
async function readEntry(entry) {{
  if (entry.installed) {{
    const p=await jget('/api/skill-installed-file?name='+encodeURIComponent(entry.installed)+'&rel='+encodeURIComponent(entry.rel));
    if (p.error) throw new Error(p.error); return p.body||'';
  }}
  if (entry.file) return await entry.file.text();
  const buffer=selectedSource.zipBuffer, v=new DataView(buffer), p=entry.offset;
  if (v.getUint32(p,true) !== 0x04034b50) throw new Error('ZIP 文件项损坏');
  const start=p+30+v.getUint16(p+26,true)+v.getUint16(p+28,true);
  const bytes=new Uint8Array(buffer,start,entry.size);
  if (entry.method === 0) return new TextDecoder().decode(bytes);
  if (entry.method !== 8) throw new Error('暂不支持该 ZIP 压缩方式');
  const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new TextDecoder().decode(await new Response(stream).arrayBuffer());
}}
function showSelection() {{
  selectedSource.entries.forEach(e=>e.selected=true);
  updateSelectionMeta();
  renderTree(selectedSource.entries);
  document.getElementById('preview').textContent='点击上方文件查看内容；确认后再导入';
  document.getElementById('btn-import').disabled=false;
}}
function updateSelectionMeta() {{
  const total=selectedSource.entries.length, selected=selectedSource.entries.filter(e=>e.selected !== false).length;
  const count=selectedSource.kind === 'folder' ? selected+'/'+total+' files selected' : total+' files';
  document.getElementById('prev-meta').textContent='['+selectedSource.kind+'] '+selectedSource.name+' · '+count+' · 尚未上传';
}}
async function acceptSelection(kind, list) {{
  const chosen=Array.from(list||[]); if (!chosen.length) return;
  if (kind === 'folder') {{
    const top=(chosen[0].webkitRelativePath||'').split('/')[0];
    const entries=chosen.map(file => {{
      const path=file.webkitRelativePath||file.name;
      return {{file,path,rel:top && path.startsWith(top+'/') ? path.slice(top.length+1) : path}};
    }}).filter(e=>!hiddenPath(e.rel)).sort((a,b)=>a.rel.localeCompare(b.rel));
    selectedSource={{kind:'folder',name:top||'folder',entries}};
  }} else {{
    const file=chosen[0], lower=file.name.toLowerCase();
    if (!lower.endsWith('.md') && !lower.endsWith('.markdown') && !lower.endsWith('.zip')) throw new Error('请选择 SKILL.md、Markdown 或 ZIP');
    if (lower.endsWith('.zip')) {{
      const zipBuffer=await file.arrayBuffer();
      selectedSource={{kind:'zip',name:file.name,zipBuffer,entries:zipEntries(zipBuffer),uploadFiles:[file],uploadPaths:[file.name]}};
    }} else {{
      selectedSource={{kind:'md',name:file.name,entries:[{{file,path:file.name,rel:file.name}}],uploadFiles:[file],uploadPaths:[file.name]}};
    }}
  }}
  showSelection();
}}
document.getElementById('btn-preview').onclick=() => {{
  const kind=document.getElementById('pick-kind').value;
  document.getElementById(kind === 'folder' ? 'pick-dir' : 'pick-file').click();
}};
document.getElementById('pick-dir').onchange=async e => {{ try {{ await acceptSelection('folder',e.target.files); }} catch(x) {{ document.getElementById('preview').textContent=String(x.message||x); }} }};
document.getElementById('pick-file').onchange=async e => {{ try {{ await acceptSelection('file',e.target.files); }} catch(x) {{ document.getElementById('preview').textContent=String(x.message||x); }} }};
document.getElementById('tree').addEventListener('click',async e => {{
  const a=e.target.closest('a[data-file]'); if (!a) return; e.preventDefault();
  try {{ document.getElementById('preview').textContent=(await readEntry(selectedSource.entries[Number(a.dataset.file)])).slice(0,20000); }}
  catch(x) {{ document.getElementById('preview').textContent=String(x.message||x); }}
}});
document.getElementById('tree').addEventListener('change',e => {{
  const file=e.target.closest('input[data-check]'), dir=e.target.closest('input[data-dir]');
  if (file) selectedSource.entries[Number(file.dataset.check)].selected=file.checked;
  if (dir) {{
    const prefix=dir.dataset.dir ? dir.dataset.dir+'/' : '';
    selectedSource.entries.filter(item=>item.rel.startsWith(prefix)).forEach(item=>item.selected=dir.checked);
  }}
  updateSelectionMeta(); renderTree(selectedSource.entries);
}});
document.getElementById('btn-import').onclick=async () => {{
  if (!selectedSource) return;
  try {{
    let uploadFiles=selectedSource.uploadFiles, uploadPaths=selectedSource.uploadPaths;
    if (selectedSource.kind === 'folder') {{
      const entries=selectedSource.entries.filter(e=>e.selected !== false);
      if (!entries.length) throw new Error('请至少勾选一个文件');
      uploadFiles=entries.map(e=>e.file);
      uploadPaths=entries.map(e=>selectedSource.name+'/'+e.rel);
    }}
    const data=new FormData(); data.append('kind',selectedSource.kind === 'folder' ? 'folder' : 'file'); data.append('paths',JSON.stringify(uploadPaths));
    uploadFiles.forEach(f=>data.append('files',f,f.name));
    const r=await fetch('/api/skill-upload',{{method:'POST',body:data,headers:{{'Accept':'application/json'}}}});
    const body=await r.text(); if (!r.ok) throw new Error(body); const j=JSON.parse(body);
    document.getElementById('preview').textContent='已导入 '+j.name;
    document.getElementById('prev-meta').textContent=document.getElementById('prev-meta').textContent.replace('尚未上传','已上传并导入');
    loadCat();
  }} catch(e) {{ document.getElementById('preview').textContent=String(e.message||e); }}
}};
document.getElementById('cat').addEventListener('change', async (e) => {{
  const cb = e.target.closest('input[data-en]');
  if (cb) {{
    await jpost('/api/skill-enable', {{name: cb.dataset.en, who: cb.dataset.who, on: cb.checked ? '1' : '0'}});
    loadCat();
    return;
  }}
  const sel = e.target.closest('select[data-teach]');
  if (sel && sel.value) {{
    await jpost('/api/skill-teach', {{dt: sel.value, skill: sel.dataset.teach}});
    sel.value = '';
    loadLog();
  }}
}});
document.getElementById('cat').addEventListener('click', async (e) => {{
  const view = e.target.closest('[data-view]');
  if (view) {{
    const p=await jget('/api/skill-tree?name='+encodeURIComponent(view.dataset.view));
    if (p.error) {{ document.getElementById('preview').textContent=p.error; return; }}
    selectedSource={{kind:'installed',name:p.name,entries:(p.files||[]).map(rel=>({{rel,installed:view.dataset.view}}))}};
    document.getElementById('prev-meta').textContent='[installed] '+p.name+' · '+selectedSource.entries.length+' files · 只读';
    renderTree(selectedSource.entries);
    document.getElementById('preview').textContent='点击上方文件查看已安装内容';
    document.getElementById('btn-import').disabled=true;
    return;
  }}
  const ok = e.target.closest('[data-ok]');
  const fail = e.target.closest('[data-fail]');
  const btn = ok || fail;
  if (!btn) return;
  const dt = tunnels[0] || '';
  if (!dt) return;
  await jpost('/api/skill-used', {{dt, name: btn.dataset.ok || btn.dataset.fail, ok: ok ? '1' : '0'}});
  loadLog();
}});
loadCat();
loadLog();
</script>
    """
    return _shell(_nav("skills"), body, "dt web · skills")


def tunnels_page(selected: str = "") -> str:
    rows = _tunnels()
    names = json.dumps(rows, ensure_ascii=False)
    data = {}
    if selected:
        try:
            data = load(find_dt(selected))
        except SystemExit:
            data = {}
    op = data.get("op") or ""
    run = data.get("run") or ""
    trigger_out = (
        html.escape(_capture(op)) if selected else "选定隧道后显示 trigger（op_*）"
    )
    bullet_out = (
        html.escape(_capture(run)) if selected else "选定隧道后显示 bullet（run_*）"
    )
    meta = ""
    if selected and data:
        meta = (
            f"{html.escape(selected)} · op=<code>{html.escape(op)}</code> · "
            f"run=<code>{html.escape(run)}</code> · "
            f"DST={'yes' if oc_ops.is_dst(data) else 'no'}"
        )
    sel = html.escape(selected)
    body = f"""
    <div class="top"><h1>隧道</h1><p>模糊搜索选定 DT，向 trigger 提交，下方轮询 op / run 屏</p></div>
    <div class="content">
      <details class="card" id="create-panel">
        <summary><b>新建隧道 / 运行模式</b></summary>
        <form id="createf" class="models" style="margin-top:12px">
          <div class="field"><label>名称</label><input id="new-name" required placeholder="myapp"></div>
          <div class="field"><label>工作目录</label><input id="new-dir" placeholder="本地路径或远端 /workspace"></div>
          <div class="field"><label>运行位置</label><select id="new-local"><option value="0">沿用当前配置</option><option value="1">强制仅本地</option></select></div>
          <div class="field"><label>Server（留空沿用配置）</label><input id="new-server" placeholder="tom7r 或 user@host"></div>
          <div class="field"><label>Container</label><input id="new-container" placeholder="可选"></div>
          <div class="field"><label>trigger 客户端</label><select id="new-trigger-tool"><option value="opencode">OpenCode</option><option value="codex">Codex</option><option value="claude">Claude Code</option></select></div>
          <div class="field"><label>bullet 客户端</label><select id="new-bullet-tool"><option value="opencode">OpenCode</option><option value="codex">Codex</option><option value="claude">Claude Code</option></select></div>
          <button type="submit">创建</button>
        </form>
        <form id="modef" class="models" style="margin-top:14px">
          <div class="field"><label>模式</label><select id="cfg-mode"><option value="local">仅本地</option><option value="hub">Hub 同步</option></select></div>
          <div class="field"><label>Client</label><input id="cfg-client" placeholder="tm_laptop"></div>
          <div class="field"><label>Workspace</label><input id="cfg-workspace" placeholder="/workspace"></div>
          <div class="field"><label>Hub Server</label><input id="cfg-server" placeholder="tom7r"></div>
          <div class="field"><label>Hub User</label><input id="cfg-user" placeholder="andy"></div>
          <button type="submit" class="ghost">安全切换模式</button>
        </form>
      </details>
      <div class="card pick">
        <label>选择隧道（dt ls）</label>
        <input id="q" type="search" placeholder="输入名称模糊搜索…" value="{sel}" autocomplete="off">
        <div class="hits" id="hits"></div>
        <div class="meta" id="meta" style="margin-top:8px">{meta}</div>
        <div class="btabs" id="btabs" style="margin-top:12px"></div>
        <div class="recent" id="recent" style="margin-top:8px"></div>
        <div class="sync" id="syncbox" style="margin-top:10px">选定隧道后显示会话同步</div>
        <div class="sync" id="clientbox" style="margin-top:8px">
          <span id="client-op">trigger client —</span> · <span id="client-run">bullet client —</span>
        </div>
        <div class="sync" id="healthbox" style="margin-top:8px">health —</div>
        <div class="models" id="lifecycle">
          <div class="field"><label>freeze 范围</label><select id="freeze-side"><option value="both">trigger + bullet</option><option value="trigger">trigger</option><option value="bullet">bullet</option></select></div>
          <div class="field"><label>远端客户端</label><select id="freeze-tool"><option value="auto">自动识别</option><option value="opencode">OpenCode</option><option value="codex">Codex</option><option value="claude">Claude Code</option></select></div>
          <button type="button" class="ghost" id="btn-freeze">Freeze</button>
          <button type="button" class="ghost" id="btn-resume">Resume</button>
          <button type="button" class="ghost" id="btn-reconnect">重连入口</button>
          <button type="button" class="ghost" id="btn-drop">Drop</button>
          <button type="button" class="ghost" id="btn-health">立即健康检查</button>
          <button type="button" class="ghost" id="btn-recover">恢复</button>
          <button type="button" class="ghost" id="btn-auto-recover">自动恢复：切换</button>
          <button type="button" class="ghost" id="btn-hub-push">Hub Push</button>
          <button type="button" class="ghost" id="btn-hub-pull">Hub Pull</button>
          <button type="button" class="ghost" id="btn-remove">删除隧道</button>
        </div>
        <div class="models" id="models">
          <div class="field"><label>trigger 模型</label><input id="m-op" placeholder="模糊搜索 provider/id" autocomplete="off"><div class="mhits" id="mh-op"></div></div>
          <div class="field"><label>bullet 模型</label><input id="m-run" placeholder="模糊搜索 provider/id" autocomplete="off"><div class="mhits" id="mh-run"></div></div>
          <button type="button" id="btn-model-op">切换 trigger</button>
          <button type="button" id="btn-model-run">切换 bullet</button>
          <button type="button" class="ghost" id="btn-auto-op" hidden>trigger 转为 auto</button>
        </div>
      </div>
      <div class="card">
        <h2>trigger 问答</h2>
        <div class="thread" id="thread"></div>
      </div>
      <div class="card">
        <div class="h2row">
          <h2>发给 trigger（op_*）</h2>
          <div class="lamps">
            <span class="lamp-wrap"><i class="lamp gray" id="lamp-op"></i> trigger</span>
            <span class="lamp-wrap"><i class="lamp gray" id="lamp-run"></i> bullet</span>
          </div>
        </div>
        <form id="sendf">
          <input type="hidden" name="t" id="tname" value="{sel}">
          <textarea name="text" id="box" rows="10" placeholder="提交后 send-keys 到 trigger pane" {"disabled" if not selected else ""}></textarea>
          <div style="margin-top:8px"><button type="submit" {"disabled" if not selected else ""}>提交</button></div>
        </form>
      </div>
      <div class="card">
        <div class="h2row pollhead idle" id="pollhead">
          <h2>轮询状态</h2>
          <i class="spin" id="pollspin"></i>
        </div>
        <div class="log idle" id="log"></div>
      </div>
      <div class="card">
        <h2>trigger 会话 · <span id="oplabel">{html.escape(op or "op_*")}</span></h2>
        <pre class="out" id="opout">{trigger_out}</pre>
      </div>
      <div class="card">
        <h2>bullet 会话 · <span id="runlabel">{html.escape(run or "run_*")}</span></h2>
        <pre class="out" id="runout">{bullet_out}</pre>
      </div>
    </div>
<script>
let rows = {names};
const hits = document.getElementById('hits');
const q = document.getElementById('q');
const tname = document.getElementById('tname');
const meta = document.getElementById('meta');
const clientOp = document.getElementById('client-op');
const clientRun = document.getElementById('client-run');
const healthBox = document.getElementById('healthbox');
const logEl = document.getElementById('log');
const box = document.getElementById('box');
const opout = document.getElementById('opout');
const runout = document.getElementById('runout');
const oplabel = document.getElementById('oplabel');
const runlabel = document.getElementById('runlabel');
const sendf = document.getElementById('sendf');
const lampOp = document.getElementById('lamp-op');
const lampRun = document.getElementById('lamp-run');
const autoOp = document.getElementById('btn-auto-op');
const threadEl = document.getElementById('thread');
let chosen = {json.dumps(selected)};
const LOG_MAX = 200;
const THREAD_MAX = 60;
const LONG_RUNNING_MS = 600000;
const STALLED_MS = 600000;
const ATTENTION_MS = 1800000;
const TABS_KEY = 'dual-tmux:web-state:v1';
let tabSeq = 1;
const tabs = [];
let activeTab = null;
let visitHistory = {{}};
let saveTimer = 0;
let lastServerState = '';
function esc(s) {{ return String(s||'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]); }}

async function loadConfig() {{
  try {{
    const r=await fetch('/api/config'), c=await r.json();
    document.getElementById('cfg-mode').value=c.mode||'local';
    document.getElementById('cfg-client').value=c.client||'';
    document.getElementById('cfg-workspace').value=c.workspace||'';
    document.getElementById('cfg-server').value=c.server||'';
    document.getElementById('cfg-user').value=c.user||'';
  }} catch(_) {{}}
}}

function emptyState(name) {{
  return {{
    id: tabSeq++,
    name: name || '',
    lastOp: '', lastRun: '', lastSent: 0, waiting: false, pollQuiet: 0,
    opAtSend: '', lastAsk: '', lastPollKey: '', lastMeaningfulKey: '', waitStartedAt: 0,
    lastCompletion: '', completionAtSend: '', lastProgressAt: 0,
    longWarned: false, stallWarned: false, attentionWarned: false,
    finalOp: 'gray', finalRun: 'gray',
    resumeTriedAt: 0,
    thread: [], log: [],
  }};
}}
function historyState(name) {{
  const item=visitHistory[name]||{{name,firstVisitedAt:'',lastVisitedAt:'',visits:0,thread:[],log:[],finalOp:'gray',finalRun:'gray'}};
  visitHistory[name]=item; return item;
}}
function stateFromHistory(name) {{
  const st=emptyState(name), item=historyState(name);
  st.finalOp=item.finalOp||'gray'; st.finalRun=item.finalRun||'gray';
  st.thread=Array.isArray(item.thread)?item.thread.slice(-THREAD_MAX):[];
  st.log=Array.isArray(item.log)?item.log.slice(-LOG_MAX):[];
  return st;
}}
function statePayload() {{
  tabs.filter(st=>st.name).forEach(st => {{
    const item=historyState(st.name);
    item.finalOp=st.finalOp||'gray'; item.finalRun=st.finalRun||'gray';
    item.thread=(st.thread||[]).slice(-THREAD_MAX).map(x=>({{...x,text:String(x.text||'').slice(0,8000)}}));
    item.log=(st.log||[]).slice(-100).map(x=>({{...x,text:String(x.text||'').slice(0,1000)}}));
  }});
  return {{version:1,open_tabs:tabs.filter(st=>st.name).map(st=>st.name),active:activeTab&&activeTab.name||'',history:visitHistory}};
}}
function saveTabs() {{
  const payload=statePayload(), raw=JSON.stringify(payload);
  try {{ localStorage.setItem(TABS_KEY,raw); }} catch (_) {{}}
  renderRecent();
  if (raw===lastServerState) return;
  clearTimeout(saveTimer);
  saveTimer=setTimeout(async()=>{{
    try {{
      const r=await fetch('/api/web-state',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:raw}});
      if (r.ok) lastServerState=raw;
    }} catch (_) {{}}
  }},120);
}}
function migrateLocalState() {{
  try {{
    const current=JSON.parse(localStorage.getItem(TABS_KEY)||'null');
    if (current&&current.history) return current;
    const old=JSON.parse(localStorage.getItem('dual-tmux:tunnel-tabs:v1')||'null');
    if (!old||!Array.isArray(old.tabs)) return null;
    const now=new Date().toISOString(), history={{}};
    old.tabs.forEach(item=>{{ if(item&&item.name) history[item.name]={{...item,name:item.name,firstVisitedAt:now,lastVisitedAt:now,visits:1}}; }});
    const activeItem=old.tabs[Math.min(Number(old.active)||0,Math.max(0,old.tabs.length-1))];
    return {{version:1,open_tabs:old.tabs.map(x=>x.name).filter(Boolean),active:activeItem&&activeItem.name||'',history}};
  }} catch (_) {{ return null; }}
}}
async function restoreTabs(selectedName) {{
  let saved=null;
  try {{ const r=await fetch('/api/web-state'); if(r.ok) saved=await r.json(); }} catch (_) {{}}
  if (!saved||!saved.history||!Object.keys(saved.history).length) saved=migrateLocalState()||saved||{{}};
  visitHistory=saved&&saved.history&&typeof saved.history==='object'?saved.history:{{}};
  (Array.isArray(saved.open_tabs)?saved.open_tabs:[]).forEach(name=>{{
    if (rows.some(row=>row.name===name)&&!tabs.some(st=>st.name===name)) tabs.push(stateFromHistory(name));
  }});
  const wanted=selectedName||(saved.active||'');
  let st=tabs.find(item=>item.name===wanted);
  if (!st&&wanted&&rows.some(row=>row.name===wanted)) {{ st=stateFromHistory(wanted); tabs.push(st); }}
  if (st) {{ activate(st); return; }}
  if (tabs.length) {{ activate(tabs[0]); return; }}
  addTab('');
}}
function colorOf(st) {{
  if (!st || !st.name) return 'gray';
  if (st.waiting) return 'yellow';
  if (st.finalOp === 'red' || st.finalRun === 'red') return 'red';
  if (st.finalOp === 'green' || st.finalRun === 'green') return 'green';
  return 'gray';
}}
function renderRecent() {{
  const el=document.getElementById('recent'); if(!el) return;
  const open=new Set(tabs.map(st=>st.name));
  const items=Object.values(visitHistory).filter(item=>item&&item.name&&!open.has(item.name)&&rows.some(row=>row.name===item.name))
    .sort((a,b)=>String(b.lastVisitedAt||'').localeCompare(String(a.lastVisitedAt||''))).slice(0,8);
  el.innerHTML=items.length?'<span>最近访问</span>'+items.map(item=>'<button type="button" data-reopen="'+esc(item.name)+'"><b>'+esc(item.name)+'</b><small>'+Number(item.visits||0)+' 次 · '+esc(item.lastVisitedAt?new Date(item.lastVisitedAt).toLocaleString():'')+'</small></button>').join(''):'';
}}
function touchVisit(st) {{
  if(!st||!st.name) return;
  const item=historyState(st.name), now=new Date().toISOString();
  if(!item.firstVisitedAt) item.firstVisitedAt=now;
  item.lastVisitedAt=now; item.visits=Number(item.visits||0)+1;
}}
function renderTabs() {{
  const el = document.getElementById('btabs');
  el.innerHTML = tabs.map(st => {{
    const on = st === activeTab ? ' active' : '';
    const c = colorOf(st);
    const label = st.name || '未选隧道';
    return '<div class="btab '+c+on+'" data-id="'+st.id+'"><i class="dot"></i><span>'+label+'</span><button class="x" data-close="'+st.id+'" type="button">×</button></div>';
  }}).join('') + '<button class="btab-add" id="tabadd" type="button">+</button>';
  saveTabs();
}}
function applyState(st) {{
  const preserveThreadScroll = chosen===st.name && threadEl.children.length &&
    threadEl.scrollHeight-threadEl.scrollTop-threadEl.clientHeight > 32;
  const priorThreadScroll = threadEl.scrollTop;
  chosen = st.name;
  tname.value = st.name || '';
  q.value = st.name || '';
  box.disabled = !st.name;
  sendf.querySelector('button').disabled = !st.name;
  const row = rows.find(r => r.name === st.name);
  const mop = document.getElementById('m-op');
  const mrun = document.getElementById('m-run');
  if (row) {{
    oplabel.textContent = row.op;
    runlabel.textContent = row.run;
    mop.value = row.trigger_model || '';
    mrun.value = row.bullet_model || '';
    meta.innerHTML = st.name+' · op=<code>'+row.op+'</code> · run=<code>'+row.run+'</code> · DST='+(row.dst?'yes':'no');
    const cv=c=>c&&c.name?(c.name+(c.version?' '+c.version:'')+' · '+(c.location||'unknown')):'—';
    clientOp.textContent='trigger client '+cv(row.trigger_client);
    clientRun.textContent='bullet client '+cv(row.bullet_client);
    const hs=(row.health&&row.health.status)||'disabled';
    const he=(row.health&&row.health.last_error)||'—';
    healthBox.textContent='health '+hs+' · auto '+(row.auto_recover?'on':'off')+' · '+he;
  }} else {{
    mop.value = '';
    mrun.value = '';
    oplabel.textContent = 'op_*';
    runlabel.textContent = 'run_*';
    meta.textContent = st.name ? st.name : '未选隧道';
    clientOp.textContent='trigger client —';
    clientRun.textContent='bullet client —';
    healthBox.textContent='health —';
  }}
  setLamp(lampOp, st.waiting ? 'yellow' : st.finalOp);
  setLamp(lampRun, st.waiting ? 'yellow' : st.finalRun);
  setPollBusy(st.waiting);
  threadEl.innerHTML = '';
  (st.thread || []).forEach(item => addBubble(item.kind, item.text, item.extra, true, false));
  threadEl.scrollTop = preserveThreadScroll ? priorThreadScroll : threadEl.scrollHeight;
  logEl.innerHTML = '';
  (st.log || []).forEach(item => logLine(item.kind, item.text, true));
  history.replaceState(null, '', st.name ? ('/tunnels?t='+encodeURIComponent(st.name)) : '/tunnels');
}}
function activate(st) {{
  activeTab = st;
  touchVisit(st);
  renderTabs();
  applyState(st);
  if (st.name) {{ ensureResumed(st); tick(); }}
}}
function addTab(name) {{
  const st = name ? stateFromHistory(name) : emptyState('');
  tabs.push(st);
  activate(st);
  return st;
}}
function closeTab(id) {{
  const i = tabs.findIndex(t => t.id === id);
  if (i < 0) return;
  const was = tabs[i] === activeTab;
  statePayload();
  tabs.splice(i, 1);
  if (!tabs.length) addTab('');
  else if (was) activate(tabs[Math.max(0, i-1)]);
  else renderTabs();
}}

function setLamp(el, color) {{
  el.className = 'lamp ' + color;
}}
function setPollBusy(on) {{
  logEl.className = 'log ' + (on ? 'busy' : 'idle');
  const head = document.getElementById('pollhead');
  if (head) head.className = 'h2row pollhead ' + (on ? 'busy' : 'idle');
}}
function addBubble(kind, text, extra, skipSave, forceFollow) {{
  const follow = forceFollow === undefined
    ? threadEl.scrollHeight-threadEl.scrollTop-threadEl.clientHeight <= 32
    : forceFollow;
  const b = document.createElement('div');
  b.className = 'bubble ' + kind;
  const who = document.createElement('div');
  who.className = 'who';
  who.textContent = kind === 'ask' ? '提问' : (kind === 'fail' ? '失败' : '回复');
  const body = document.createElement('div');
  body.className = 'body';
  body.textContent = text || '';
  b.appendChild(who);
  b.appendChild(body);
  extra = extra || {{}};
  if(!extra.ts) extra.ts=new Date().toISOString();
  const bits = [];
  if (extra.model) bits.push(extra.model);
  if (extra.elapsed) bits.push(extra.elapsed);
  bits.push(new Date(extra.ts).toLocaleString());
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = bits.join(' · ');
  b.appendChild(meta);
  threadEl.appendChild(b);
  while (threadEl.children.length > THREAD_MAX) threadEl.removeChild(threadEl.firstChild);
  if (follow) threadEl.scrollTop = threadEl.scrollHeight;
  if (!skipSave && activeTab) {{
    activeTab.thread = activeTab.thread || [];
    activeTab.thread.push({{kind, text, extra: extra || {{}}}});
    if (activeTab.thread.length > THREAD_MAX) activeTab.thread.shift();
    saveTabs();
  }}
}}
function summarize(text) {{
  const lines = (text || '').split('\\n').map(s => s.trim()).filter(Boolean);
  const skip = /^(ok |skip |· |err |Build |% |░|▒|▓|┌|└|│)/;
  const good = lines.filter(l => !skip.test(l) && l.length > 8);
  const pick = good.slice(-3);
  if (pick.length) return pick.join(' / ').slice(0, 160);
  return (lines.slice(-1)[0] || 'trigger 有输出').slice(0, 120);
}}
function paneDelta(before, after) {{
  const a = after || '';
  const b = before || '';
  if (a.startsWith(b)) return a.slice(b.length).trim();
  const lines = a.trim().split('\\n').filter(Boolean);
  return lines.slice(-24).join('\\n');
}}

function logLine(kind, text, skipSave) {{
  const row = document.createElement('div');
  row.className = 'row';
  const tag = document.createElement('span');
  tag.className = 'tag ' + kind;
  tag.textContent = kind;
  const msg = document.createElement('span');
  msg.className = 'msg';
  msg.textContent = text;
  row.appendChild(tag);
  row.appendChild(msg);
  logEl.appendChild(row);
  while (logEl.children.length > LOG_MAX) logEl.removeChild(logEl.firstChild);
  logEl.scrollTop = logEl.scrollHeight;
  if (!skipSave && activeTab) {{
    activeTab.log = activeTab.log || [];
    activeTab.log.push({{kind, text}});
    if (activeTab.log.length > LOG_MAX) activeTab.log.shift();
    saveTabs();
  }}
}}
function logFor(st,kind,text) {{
  if (activeTab===st) {{ logLine(kind,text); return; }}
  st.log=st.log||[]; st.log.push({{kind,text}});
  if (st.log.length>LOG_MAX) st.log.shift();
  saveTabs();
}}

function match(row, s) {{
  s = (s || '').toLowerCase();
  if (!s) return true;
  const blob = [row.name, row.op, row.run, row.trigger, row.bullet].join(' ').toLowerCase();
  return s.split(/\\s+/).every(p => blob.includes(p));
}}
function renderHits() {{
  const s = q.value;
  const list = rows.filter(r => match(r, s)).slice(0, 20);
  hits.innerHTML = list.map(r => {{
    const kind = r.dst ? 'DST' : 'DT';
    const live = (r.op_live || r.run_live) ? 'live' : 'down';
    return '<a href="#" data-name="'+r.name+'"><b>'+r.name+'</b> <span class="sub">'+kind+' · '+live+' · '+r.op+' / '+r.run+'</span></a>';
  }}).join('') || '<div class="sub" style="padding:8px">无匹配</div>';
  hits.style.display = 'block';
}}
async function refreshRows(showHits=false) {{
  try {{
    const r=await fetch('/api/tunnels');
    if (!r.ok) return;
    const latest=await r.json();
    if (!Array.isArray(latest)) return;
    rows=latest;
    if (activeTab && activeTab.name) applyState(activeTab);
    if (showHits || hits.style.display === 'block') renderHits();
  }} catch (_) {{}}
}}
function pick(name) {{
  const row = rows.find(r => r.name === name);
  if (!row) return;
  hits.style.display = 'none';
  if (!activeTab) addTab(name);
  const existing=tabs.find(st=>st.name===name);
  if(existing&&existing!==activeTab) {{ activate(existing); return; }}
  const st = activeTab;
  const prior=historyState(name);
  st.name = name;
  st.lastOp = st.lastRun = '';
  st.waiting = false;
  st.pollQuiet = 0;
  st.opAtSend = '';
  st.lastAsk = '';
  st.lastPollKey = '';
  st.lastMeaningfulKey = '';
  st.waitStartedAt = 0;
  st.lastCompletion = '';
  st.completionAtSend = '';
  st.lastProgressAt = 0;
  st.longWarned = st.stallWarned = st.attentionWarned = false;
  st.finalOp = prior.finalOp||'gray';
  st.finalRun = prior.finalRun||'gray';
  st.thread=Array.isArray(prior.thread)?prior.thread.slice(-THREAD_MAX):[];
  st.log=Array.isArray(prior.log)?prior.log.slice(-LOG_MAX):[];
  activate(st);
  logLine('pick', '已选定 ' + name + ' · ' + row.op + ' / ' + row.run);
}}
q.addEventListener('focus', async () => {{ await refreshRows(true); }});
q.addEventListener('input', renderHits);
hits.addEventListener('click', (e) => {{
  const a = e.target.closest('a[data-name]');
  if (!a) return;
  e.preventDefault();
  pick(a.dataset.name);
}});
document.addEventListener('click', (e) => {{
  if (!e.target.closest('.pick')) hits.style.display = 'none';
}});
q.addEventListener('keydown', (e) => {{
  if (e.key === 'Enter') {{
    e.preventDefault();
    const first = hits.querySelector('a[data-name]');
    if (first) pick(first.dataset.name);
  }}
}});

let lastSync = {{}};
function sessChip(name, live, busy, prevMtime, mtime, kind) {{
  const cls = busy ? 'busy' : 'ok';
  const label = busy ? '同步中' : '已同步';
  const chg = prevMtime && mtime && prevMtime !== mtime ? ' · 更新' : '';
  const liveS = live ? 'live' : 'down';
  return '<span class="sess '+cls+'"><i class="spin"></i><b>'+ (name || '—') +'</b> '+label+chg+' · '+liveS+(mtime ? ' · '+mtime : '')+'</span>';
}}
function renderSync(s) {{
  if (!s) return;
  const el = document.getElementById('syncbox');
  const ocBusy = !!s.oc_busy;
  const tmBusy = !!s.tmux_busy;
  el.innerHTML =
    '<div class="syncbar">' +
    sessChip(s.op, s.op_live, ocBusy || tmBusy, lastSync.tmux_last, s.tmux_last, 'op') +
    sessChip(s.run, s.run_live, ocBusy || tmBusy, lastSync.oc_mtime, s.oc_mtime, 'run') +
    '</div>' +
    '<div class="row" style="margin-top:6px"><span class="k">oc 快照</span><span class="v">'+(s.oc_slug || '—')+' '+(s.oc_mtime || '')+(lastSync.oc_mtime && s.oc_mtime && lastSync.oc_mtime !== s.oc_mtime ? ' <span class="chg">更新</span>' : '')+'</span></div>';
  lastSync = s;
}}
async function ensureResumed(st) {{
  const row=rows.find(item=>item.name===st.name);
  if (!row || !row.dst || !row.auto_recover || (row.op_live && row.run_live)) return;
  if (Date.now()-(st.resumeTriedAt||0) < 30000) return;
  st.resumeTriedAt=Date.now();
  logFor(st,'resume','本机会话离线，正在自动 resume '+st.name);
  try {{
    const result=await postForm('/api/resume',{{t:st.name}});
    row.op_live=!!result.op_live; row.run_live=!!result.run_live;
    logFor(st,result.op_live&&result.run_live?'done':'err',result.resumed?'自动 resume 完成':'会话已经在线');
    if (activeTab===st) tick();
  }} catch(err) {{
    logFor(st,'err','自动 resume 失败 · '+String(err.message||err));
  }}
  renderTabs();
}}
function snap(el, next) {{
  if (next === el.textContent) return;
  el.textContent = next;
  el.scrollTop = el.scrollHeight;
}}

async function tick() {{
  const st = activeTab;
  if (!st || !st.name) return;
  const r = await fetch('/api/tunnel?t=' + encodeURIComponent(st.name));
  const j = await r.json();
  if (j.error) {{ logLine('err', j.error); return; }}
  const liveRow=rows.find(item=>item.name===st.name);
  if (liveRow) {{
    liveRow.op_live=!!j.op_live; liveRow.run_live=!!j.run_live;
    if (liveRow.dst && (!j.op_live || !j.run_live)) ensureResumed(st);
  }}
  snap(opout, j.op_text || '');
  snap(runout, j.run_text || '');
  if (j.sync) renderSync(j.sync);
  autoOp.hidden = !st.name || j.trigger_tool !== 'opencode' || j.op_auto !== false || !j.op_live;
  document.getElementById('btn-model-op').disabled = j.trigger_tool !== 'opencode';
  document.getElementById('btn-model-run').disabled = j.bullet_tool !== 'opencode';
  document.getElementById('m-op').disabled = j.trigger_tool !== 'opencode';
  document.getElementById('m-run').disabled = j.bullet_tool !== 'opencode';
  if (j.trigger_model != null) {{
    const row = rows.find(r => r.name === st.name);
    if (row) {{
      row.trigger_model = j.trigger_model || row.trigger_model;
      row.bullet_model = j.bullet_model || row.bullet_model;
      if (document.activeElement !== document.getElementById('m-op'))
        document.getElementById('m-op').value = row.trigger_model || '';
      if (document.activeElement !== document.getElementById('m-run'))
        document.getElementById('m-run').value = row.bullet_model || '';
    }}
  }}
  const opChanged = j.op_text !== st.lastOp;
  const runChanged = j.run_text !== st.lastRun;
  st.lastOp = j.op_text || '';
  st.lastRun = j.run_text || '';
  const opState = j.op_live ? (j.op_cmd || 'live') : 'down';
  const runState = j.run_live ? (j.run_cmd || 'live') : 'down';
  if (st.waiting) {{
    setLamp(lampOp, 'yellow');
    setLamp(lampRun, j.run_live ? 'yellow' : 'red');
    setPollBusy(true);
    const parsed = (j.op_parsed || {{}});
    const now = Date.now();
    const age = st.waitStartedAt ? now-st.waitStartedAt : 0;
    const meaningfulKey = [parsed.body||'',parsed.completion_id||''].join('|');
    const completionChanged = !!parsed.completion_id && parsed.completion_id !== st.completionAtSend;
    if (meaningfulKey && meaningfulKey !== st.lastMeaningfulKey) {{
      st.lastProgressAt = now;
      st.lastMeaningfulKey = meaningfulKey;
    }}
    if (!j.op_live) {{
      const reply='失败 · trigger '+opState;
      addBubble('fail',reply,parsed);
      logLine('err','本轮失败 · trigger pane 已离线');
      st.finalOp='red'; st.finalRun=j.run_live?'green':'red';
      st.waiting=false; st.pollQuiet=0; st.waitStartedAt=0; st.lastPollKey='';
      setLamp(lampOp,st.finalOp); setLamp(lampRun,st.finalRun); setPollBusy(false);
      renderTabs();
    }} else if (parsed.phase === 'idle' && completionChanged) {{
      const reply=parsed.body || paneDelta(st.opAtSend,j.op_text) || '本轮已完成';
      addBubble('ans',reply,parsed);
      st.finalOp='green'; st.finalRun=j.run_live?'green':'red';
      logLine('done','本轮结束 · '+(parsed.model||'')+(parsed.elapsed?' · '+parsed.elapsed:''));
      st.waiting=false; st.pollQuiet=0; st.waitStartedAt=0; st.lastPollKey='';
      setLamp(lampOp,st.finalOp); setLamp(lampRun,st.finalRun); setPollBusy(false);
      renderTabs();
    }} else if (j.op_auto === false && parsed.phase !== 'running') {{
      const reply='trigger 当前不是 auto 模式；消息已发出，但可能在等待授权。前端已停止自动轮询，可点击上方“trigger 转为 auto”恢复原会话后继续。';
      addBubble('fail',reply,parsed);
      logLine('err','停止轮询 · trigger 非 auto 模式');
      st.finalOp='red'; st.finalRun=j.run_live?'green':'red';
      st.waiting=false; st.pollQuiet=0; st.waitStartedAt=0; st.lastPollKey='';
      setLamp(lampOp,st.finalOp); setLamp(lampRun,st.finalRun); setPollBusy(false);
      renderTabs();
    }} else if (parsed.phase === 'running') {{
      st.pollQuiet=0;
      if (age >= LONG_RUNNING_MS && !st.longWarned) {{
        logLine('poll','长任务 · 已运行 '+Math.floor(age/60000)+' 分钟，OpenCode 仍明确处于 running，继续等待');
        st.longWarned=true;
      }}
      if (st.lastProgressAt && now-st.lastProgressAt >= STALLED_MS && !st.stallWarned) {{
        logLine('err','可能停滞 · 10 分钟没有新的语义输出，但进程/TUI 仍存活；建议检查 provider');
        st.stallWarned=true;
      }}
      if (age >= ATTENTION_MS && !st.attentionWarned) {{
        logLine('err','需要关注 · 已运行 30 分钟；继续监测，不自动判失败');
        st.attentionWarned=true;
      }}
    }} else if (opChanged) {{
      const sum = parsed.body ? parsed.body.replace(/\\s+/g, ' ').slice(0, 140) : summarize(paneDelta(st.opAtSend, j.op_text) || j.op_text);
      const key = (parsed.model || '') + '|' + sum;
      if (key !== st.lastPollKey) {{
        const extra = parsed.model ? (' · ' + parsed.model + (parsed.elapsed ? ' · ' + parsed.elapsed : '')) : '';
        logLine('poll', sum + extra);
        st.lastPollKey = key;
      }}
      st.pollQuiet = 0;
    }} else {{
      st.pollQuiet += 1;
      if (st.pollQuiet === 1) logLine('poll', '等待 trigger · op=' + opState);
      if (st.pollQuiet >= 8) {{
        const fail = !j.op_live;
        const reply = fail
          ? ('失败 · trigger ' + opState)
          : (parsed.body || paneDelta(st.opAtSend, j.op_text) || '本轮无新文本');
        addBubble(fail ? 'fail' : 'ans', reply, parsed);
        st.finalOp = fail ? 'red' : 'green';
        st.finalRun = j.run_live ? 'green' : 'red';
        setLamp(lampOp, st.finalOp);
        setLamp(lampRun, st.finalRun);
        setPollBusy(false);
        const doneMsg = fail
          ? ('本轮失败 · op=' + opState)
          : ('本轮结束 · ' + (parsed.model || '') + (parsed.elapsed ? ' · ' + parsed.elapsed : '') + (parsed.body ? ' · ' + parsed.body.replace(/\\s+/g, ' ').slice(0, 80) : ''));
        logLine(fail ? 'err' : 'done', doneMsg.trim());
        st.waiting = false;
        st.pollQuiet = 0;
        st.waitStartedAt = 0;
        st.lastPollKey = '';
        renderTabs();
      }}
    }}
  }} else {{
    setPollBusy(false);
    setLamp(lampOp, st.finalOp);
    setLamp(lampRun, st.finalRun);
  }}
  st.lastCompletion = (j.op_parsed||{{}}).completion_id || st.lastCompletion;
  renderTabs();
}}
setInterval(tick, 1500);
setInterval(refreshRows, 5000);

document.getElementById('btabs').addEventListener('click', (e) => {{
  const close = e.target.closest('[data-close]');
  if (close) {{ e.stopPropagation(); closeTab(Number(close.dataset.close)); return; }}
  if (e.target.closest('#tabadd')) {{ addTab(''); return; }}
  const tab = e.target.closest('.btab');
  if (!tab) return;
  const st = tabs.find(t => t.id === Number(tab.dataset.id));
  if (st) activate(st);
}});
document.getElementById('recent').addEventListener('click',e=>{{
  const btn=e.target.closest('[data-reopen]'); if(!btn) return;
  const name=btn.dataset.reopen, existing=tabs.find(st=>st.name===name);
  if(existing) activate(existing); else addTab(name);
}});
sendf.addEventListener('submit', async (e) => {{
  e.preventDefault();
  const st = activeTab;
  if (!st || !st.name || !box.value.trim()) return;
  st.lastAsk = box.value.trim();
  const preview = st.lastAsk.replace(/\\s+/g, ' ').slice(0, 80);
  addBubble('ask', st.lastAsk);
  logLine('send', preview || '(empty)');
  try {{
    const baselineResponse=await fetch('/api/tunnel?t='+encodeURIComponent(st.name));
    const baseline=await baselineResponse.json();
    st.opAtSend=baseline.op_text||st.lastOp||'';
    st.lastCompletion=(baseline.op_parsed||{{}}).completion_id||st.lastCompletion||'';
  }} catch (_) {{ st.opAtSend=st.lastOp||''; }}
  st.waiting = true;
  st.pollQuiet = 0;
  st.waitStartedAt = Date.now();
  st.completionAtSend = st.lastCompletion || '';
  st.lastProgressAt = st.waitStartedAt;
  st.lastMeaningfulKey = '';
  st.longWarned = st.stallWarned = st.attentionWarned = false;
  setLamp(lampOp, 'yellow');
  setLamp(lampRun, 'yellow');
  setPollBusy(true);
  renderTabs();
  const body = new URLSearchParams({{ t: st.name, side: 'op', text: box.value }});
  const r = await fetch('/send', {{ method: 'POST', headers: {{ 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' }}, body }});
  if (!r.ok) {{
    const err = await r.text();
    logLine('err', err);
    addBubble('fail', err);
    st.finalOp = 'red';
    st.waiting = false;
    st.waitStartedAt = 0;
    setLamp(lampOp, 'red');
    setLamp(lampRun, st.finalRun);
    setPollBusy(false);
    renderTabs();
    return;
  }}
  st.lastSent = Date.now();
  st.waiting = true;
  st.pollQuiet = 0;
  box.value = '';
  logLine('send', '已提交到 trigger，开始轮询');
  renderTabs();
  tick();
}});
async function postForm(url, fields) {{
  const body = new URLSearchParams(fields);
  const r = await fetch(url, {{ method: 'POST', headers: {{ 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' }}, body }});
  const text = await r.text();
  if (!r.ok) throw new Error(text);
  try {{ return JSON.parse(text); }} catch {{ return {{ ok:true }}; }}
}}
function syncRowModels(j) {{
  const st = activeTab;
  if (!st || !st.name) return;
  const row = rows.find(r => r.name === st.name);
  if (!row) return;
  if (j.trigger_model != null) row.trigger_model = j.trigger_model;
  if (j.bullet_model != null) row.bullet_model = j.bullet_model;
  document.getElementById('m-op').value = row.trigger_model || '';
  document.getElementById('m-run').value = row.bullet_model || '';
}}
document.getElementById('btn-model-op').addEventListener('click', async () => {{
  const st = activeTab;
  const model = document.getElementById('m-op').value.trim();
  if (!st || !st.name || !model) return;
  logLine('send', '切换 trigger 模型 ' + model);
  try {{
    const j = await postForm('/api/model', {{ t: st.name, side: 'op', model }});
    syncRowModels(j);
    logLine('done', 'trigger 模型 ' + (j.model || model));
  }} catch (err) {{ logLine('err', String(err.message || err)); }}
}});
document.getElementById('btn-model-run').addEventListener('click', async () => {{
  const st = activeTab;
  const model = document.getElementById('m-run').value.trim();
  if (!st || !st.name || !model) return;
  logLine('send', '切换 bullet 模型 ' + model);
  try {{
    const j = await postForm('/api/model', {{ t: st.name, side: 'run', model }});
    syncRowModels(j);
    logLine('done', 'bullet 模型 ' + (j.model || model));
  }} catch (err) {{ logLine('err', String(err.message || err)); }}
}});
autoOp.addEventListener('click', async () => {{
  const st=activeTab; if(!st||!st.name) return;
  autoOp.disabled=true;
  logLine('send','正在将 trigger 转为 auto 模式');
  try {{
    const j=await postForm('/api/trigger-auto',{{t:st.name}});
    logLine('done',(j.changed?'已恢复原 trigger 会话并切换为 auto':'trigger 已是 auto 模式')+' · '+(j.pane||''));
    st.finalOp='green'; setLamp(lampOp,'green');
    await tick();
  }} catch(err) {{
    logLine('err','auto 转换失败 · '+String(err.message||err));
  }} finally {{ autoOp.disabled=false; }}
}});
document.getElementById('btn-freeze').addEventListener('click', async () => {{
  const st = activeTab;
  if (!st || !st.name) return;
  logLine('send', 'freeze ' + st.name);
  try {{
    const j = await postForm('/api/freeze', {{ t: st.name, side: document.getElementById('freeze-side').value, tool: document.getElementById('freeze-tool').value }});
    syncRowModels(j);
    const row = rows.find(r => r.name === st.name);
    if (row) row.dst = !!j.dst;
    logLine('done', 'freeze 完成 · DST=' + (j.dst ? 'yes' : 'no'));
    applyState(st);
  }} catch (err) {{ logLine('err', String(err.message || err)); }}
}});
async function tunnelAction(buttonId, url, fields, done) {{
  document.getElementById(buttonId).addEventListener('click', async () => {{
    const st=activeTab; if(!st||!st.name) return;
    try {{
      const value=typeof fields==='function'?fields(st):{{t:st.name}};
      if(value===null) return;
      const j=await postForm(url,value);
      logLine('done',done+' · '+st.name);
      await refreshRows(); await tick();
      return j;
    }} catch(err) {{ logLine('err',String(err.message||err)); }}
  }});
}}
tunnelAction('btn-resume','/api/resume',st=>({{t:st.name}}),'resume 完成');
tunnelAction('btn-reconnect','/api/tunnel/reconnect',st=>({{t:st.name}}),'入口已重连');
tunnelAction('btn-drop','/api/tunnel/drop',st=>confirm('Drop 本机 tmux，但保留绑定？')?{{t:st.name,confirm:st.name}}:null,'本机 pane 已 drop');
tunnelAction('btn-health','/api/health/probe',st=>({{t:st.name}}),'健康检查完成');
tunnelAction('btn-recover','/api/health/recover',st=>({{t:st.name}}),'恢复完成');
tunnelAction('btn-auto-recover','/api/health/auto',st=>{{const row=rows.find(r=>r.name===st.name);return {{t:st.name,enabled:row&&row.auto_recover?'0':'1'}}}},'自动恢复设置已更新');
tunnelAction('btn-hub-push','/api/hub/push',st=>({{t:st.name}}),'Hub push 完成');
tunnelAction('btn-hub-pull','/api/hub/pull',st=>({{t:st.name}}),'Hub pull 完成');
tunnelAction('btn-remove','/api/tunnel/remove',st=>{{
  const confirmName=prompt('这是破坏性操作。输入隧道全名确认删除：', '');
  return confirmName===null?null:{{t:st.name,confirm:confirmName,kill:'0'}};
}},'隧道已删除');
function bindModelPicker(inputId, hitsId) {{
  const inp = document.getElementById(inputId);
  const box = document.getElementById(hitsId);
  const wrap = inp.closest('.field');
  let timer = 0;
  async function show() {{
    const q = inp.value.trim();
    try {{
      const r = await fetch('/api/models?q=' + encodeURIComponent(q));
      const list = await r.json();
      box.innerHTML = (list || []).slice(0, 40).map(m => '<a href="#" data-m="'+m+'">'+m+'</a>').join('') || '<div class="sub" style="padding:8px">无匹配</div>';
    }} catch (err) {{
      box.innerHTML = '<div class="sub" style="padding:8px">加载失败</div>';
    }}
    box.style.display = 'block';
  }}
  inp.addEventListener('focus', show);
  inp.addEventListener('click', (e) => {{ e.stopPropagation(); show(); }});
  inp.addEventListener('input', () => {{ clearTimeout(timer); timer = setTimeout(show, 120); }});
  box.addEventListener('mousedown', (e) => e.preventDefault());
  box.addEventListener('click', (e) => {{
    const a = e.target.closest('a[data-m]');
    if (!a) return;
    e.preventDefault();
    e.stopPropagation();
    inp.value = a.dataset.m;
    box.style.display = 'none';
  }});
  document.addEventListener('click', (e) => {{
    if (!wrap.contains(e.target)) box.style.display = 'none';
  }});
}}
bindModelPicker('m-op', 'mh-op');
bindModelPicker('m-run', 'mh-run');
document.getElementById('createf').addEventListener('submit', async e => {{
  e.preventDefault();
  try {{
    const j=await postForm('/api/tunnel/create',{{
      name:document.getElementById('new-name').value.trim(),
      directory:document.getElementById('new-dir').value.trim(),
      local:document.getElementById('new-local').value,
      server:document.getElementById('new-server').value.trim(),
      container:document.getElementById('new-container').value.trim(),
      trigger_tool:document.getElementById('new-trigger-tool').value,
      bullet_tool:document.getElementById('new-bullet-tool').value
    }});
    await refreshRows();
    const name=j.data&&j.data.name||document.getElementById('new-name').value.trim();
    const existing=tabs.find(st=>st.name===name); activate(existing||addTab(name));
    logLine('done','隧道已创建 · '+name);
  }} catch(err) {{ alert(String(err.message||err)); }}
}});
document.getElementById('modef').addEventListener('submit', async e => {{
  e.preventDefault();
  if(!confirm('模式切换会先合并相关 Hub 记录再写配置。继续？')) return;
  try {{
    const j=await postForm('/api/config/switch',{{
      mode:document.getElementById('cfg-mode').value,
      client:document.getElementById('cfg-client').value.trim(),
      workspace:document.getElementById('cfg-workspace').value.trim(),
      server:document.getElementById('cfg-server').value.trim(),
      user:document.getElementById('cfg-user').value.trim(),
      confirm:'switch-mode'
    }});
    alert('已切换为 '+(j.data&&j.data.mode||'目标')+' 模式');
    await loadConfig(); await refreshRows();
  }} catch(err) {{ alert(String(err.message||err)); }}
}});
loadConfig();
restoreTabs({json.dumps(selected)});
</script>
    """
    return _shell(_nav("tunnels"), body, "dt web · 隧道")


class WebHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        import sys

        if _is_client_disconnect(sys.exc_info()[1]):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(
        self,
        code: int,
        body: str | bytes,
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _same_origin(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        request_netloc = (self.headers.get("Host") or "").lower()
        return (
            parsed.scheme == "http"
            and host in {"127.0.0.1", "localhost"}
            and parsed.netloc.lower() == request_netloc
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/tunnels":
            self._send(200, json.dumps(_tunnels()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/health":
            name = (qs.get("t") or [""])[0]
            if name:
                try:
                    data = load(find_dt(name))
                except SystemExit as exc:
                    self._send(
                        404,
                        json.dumps({"error": str(exc)}),
                        "application/json; charset=utf-8",
                    )
                    return
                payload = read_health_state(data.get("name") or name)
            else:
                payload = {row["name"]: row["health"] for row in _tunnels()}
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/capabilities":
            result = get_control_service().capabilities()
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/operations":
            result = get_control_service().operations()
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/config":
            cfg = load_config()
            self._send(
                200,
                json.dumps(
                    {
                        "mode": cfg.mode,
                        "client": cfg.client,
                        "server": cfg.server,
                        "ssh_port": cfg.ssh_port,
                        "user": cfg.user,
                        "workspace": cfg.workspace,
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/feishu/status":
            from .feishu import status

            payload = status()
            cfg = load_config()
            payload["bridge"] = cfg.server if cfg.hub_enabled else "local-only"
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/events":
            result = get_control_service().events(
                limit=min(500, int((qs.get("limit") or ["100"])[0] or 100)),
                kind=(qs.get("kind") or [""])[0],
                name=(qs.get("t") or [""])[0],
            )
            self._send(200, json.dumps(result.data), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/memory":
            name = (qs.get("t") or [""])[0]
            result = get_control_service().memory(name)
            self._send(200, json.dumps(result.data), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/web-state":
            self._send(
                200, json.dumps(_load_web_state()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/tunnel":
            name = (qs.get("t") or [""])[0]
            try:
                data = get_control_service().get_tunnel(name).data
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            op = data.get("op") or ""
            run = data.get("run") or ""
            op_text = _capture(op)
            run_text = _capture(run)
            payload = {
                "name": data.get("name"),
                "op": op,
                "run": run,
                "dst": oc_ops.is_dst(data),
                "op_live": bool(op) and tmux_ops.has_session(op),
                "run_live": bool(run) and tmux_ops.has_session(run),
                "op_cmd": tmux_ops.pane_info(op).get("cmd") if op else "",
                "run_cmd": tmux_ops.pane_info(run).get("cmd") if run else "",
                "op_text": op_text,
                "run_text": run_text,
                "op_auto": _opencode_auto(op_text),
                "op_parsed": parse_pane(
                    op_text, parser_id_for_side(data.get("trigger"))
                ).as_dict(),
                "run_parsed": parse_pane(
                    run_text, parser_id_for_side(data.get("bullet"))
                ).as_dict(),
                "trigger_model": (data.get("trigger") or {}).get("model") or "",
                "bullet_model": (data.get("bullet") or {}).get("model") or "",
                "trigger_client": (data.get("trigger") or {}).get("agent_client") or {},
                "bullet_client": (data.get("bullet") or {}).get("agent_client") or {},
                "auto_recover": bool(data.get("auto_recover")),
                "health": read_health_state(data.get("name") or name),
                "sync": _sync_info(data),
            }
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/models":
            q = ((qs.get("q") or [""])[0] or "").lower()
            models = oc_ops.list_models()
            if q:
                parts = [p for p in q.split() if p]
                models = [m for m in models if all(p in m.lower() for p in parts)]
            self._send(200, json.dumps(models[:80]), "application/json; charset=utf-8")
            return
        if parsed.path in {"/", "/dashboard"}:
            self._send(200, dashboard_page())
            return
        if parsed.path in {"/tunnels", "/t"}:
            self._send(200, tunnels_page((qs.get("t") or [""])[0]))
            return
        if parsed.path == "/feishu":
            self._send(200, feishu_page())
            return
        if parsed.path == "/feishu/callback":
            from .feishu import FeishuError, PairingService

            try:
                identity = PairingService().callback(
                    (qs.get("state") or [""])[0], (qs.get("code") or [""])[0]
                )
                self._send(
                    200,
                    _shell(
                        _nav("feishu"),
                        '<div class="content"><div class="card"><h1>飞书绑定成功</h1><p>可以关闭此页面并回到 dt Web。</p></div></div>',
                        "dt web · 飞书绑定成功",
                    ),
                )
            except FeishuError as exc:
                self._send(400, json.dumps(exc.as_dict()), "application/json; charset=utf-8")
            return
        if parsed.path in {"/guide", "/help"}:
            self._send(200, guide_page())
            return
        if parsed.path in {"/skills"}:
            self._send(200, skills_page())
            return
        if parsed.path == "/memory":
            self._send(200, memory_page())
            return
        if parsed.path == "/events":
            self._send(200, events_page())
            return
        if parsed.path == "/doctor":
            self._send(200, doctor_page())
            return
        if parsed.path == "/api/skills":
            self._send(
                200,
                json.dumps(skillmgr.list_catalog()),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/skill-tree":
            name = (qs.get("name") or [""])[0]
            try:
                self._send(
                    200,
                    json.dumps(skillmgr.skill_tree(name)),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    404,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-installed-file":
            name = (qs.get("name") or [""])[0]
            rel = (qs.get("rel") or [""])[0]
            try:
                body = skillmgr.read_skill_file(name, rel)
                self._send(
                    200,
                    json.dumps({"body": body, "rel": rel}),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    404,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-preview":
            src = (qs.get("src") or [""])[0]
            try:
                self._send(
                    200,
                    json.dumps(skillmgr.preview_source(src)),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    400,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-file":
            src = (qs.get("src") or [""])[0]
            rel = (qs.get("rel") or [""])[0]
            try:
                body = skillmgr.read_source_file(src, rel)
                self._send(
                    200,
                    json.dumps({"body": body, "rel": rel}),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    400,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-body":
            name = (qs.get("name") or [""])[0]
            try:
                self._send(
                    200,
                    json.dumps({"body": skillmgr.skill_body(name)}),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    404,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-log":
            n = int((qs.get("n") or ["40"])[0] or 40)
            self._send(
                200,
                json.dumps(skillmgr.read_log(limit=n)),
                "application/json; charset=utf-8",
            )
            return
        self._send(404, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._same_origin():
            self._send(
                403,
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "origin_rejected",
                            "message": "Web control writes require a local same-origin request",
                            "detail": {},
                        },
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 30 * 1024 * 1024:
            self._send(413, "[err] upload is too large", "text/plain; charset=utf-8")
            return
        raw_bytes = self.rfile.read(length)
        if parsed.path.startswith("/api/feishu/"):
            from .feishu import AppRegistrationService, FeishuError, uninstall

            try:
                payload = json.loads(raw_bytes.decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise FeishuError("invalid_request", "JSON object required")
                if parsed.path == "/api/feishu/pair":
                    if payload:
                        raise FeishuError("invalid_request", "scan-to-create takes no App credentials")
                    result = AppRegistrationService().begin()
                    import segno

                    result["qr"] = segno.make(result["authorization_url"]).svg_data_uri(scale=5)
                    result["ok"] = True
                elif parsed.path == "/api/feishu/poll":
                    result = {"ok": True, **AppRegistrationService().poll()}
                elif parsed.path == "/api/feishu/unbind":
                    result = {"ok": True, **uninstall()}
                else:
                    self._send(404, "not found")
                    return
            except (json.JSONDecodeError, FeishuError) as exc:
                body = exc.as_dict() if isinstance(exc, FeishuError) else {
                    "ok": False,
                    "error": {"code": "invalid_json", "message": "invalid JSON", "detail": {}},
                }
                self._send(400, json.dumps(body), "application/json; charset=utf-8")
                return
            self._send(200, json.dumps(result), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/web-state":
            try:
                payload = json.loads(raw_bytes.decode("utf-8"))
                saved = _save_web_state(payload)
            except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps(saved), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/skill-upload":
            try:
                fields, files = _multipart(
                    raw_bytes, self.headers.get("Content-Type") or ""
                )
                paths = json.loads(fields.get("paths") or "[]")
                if not isinstance(paths, list) or not all(
                    isinstance(p, str) for p in paths
                ):
                    raise SystemExit("[err] invalid upload paths")
                imported = skillmgr.import_upload(
                    fields.get("kind") or "", paths, files
                )
            except (SystemExit, ValueError, zipfile.BadZipFile) as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(
                200,
                json.dumps({"ok": True, "name": imported}),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/memory/fact":
            raw = raw_bytes.decode("utf-8")
            form = parse_qs(raw)
            value_raw = (form.get("value") or [""])[0]
            try:
                value = json.loads(value_raw)
            except json.JSONDecodeError:
                value = value_raw
            try:
                result = get_control_service().put_memory_fact(
                    (form.get("key") or [""])[0],
                    value,
                    (form.get("t") or [""])[0],
                )
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/memory/note":
            raw = raw_bytes.decode("utf-8")
            form = parse_qs(raw)
            try:
                result = get_control_service().add_memory_note(
                    (form.get("t") or [""])[0],
                    (form.get("body") or [""])[0],
                    (form.get("title") or [""])[0],
                )
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/doctor/run":
            result = get_control_service().doctor()
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        raw = raw_bytes.decode("utf-8")
        form = parse_qs(raw)
        name = (form.get("t") or [""])[0]
        if parsed.path == "/api/resume":
            try:
                result = _resume_tunnel(name)
            except (SystemExit, ControlError) as exc:
                status = exc.status if isinstance(exc, ControlError) else 409
                self._send(status, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps(result), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/trigger-auto":
            try:
                result = _switch_trigger_auto(name)
            except SystemExit as exc:
                self._send(409, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps(result), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/skill-import":
            try:
                imported = skillmgr.import_skill((form.get("src") or [""])[0])
            except SystemExit as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(
                200,
                json.dumps({"ok": True, "name": imported}),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/skill-enable":
            try:
                skillmgr.set_enabled(
                    (form.get("name") or [""])[0],
                    (form.get("who") or ["trigger"])[0],
                    (form.get("on") or ["1"])[0] != "0",
                )
            except SystemExit as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/skill-teach":
            try:
                from . import tmux as tmux_send
                from .cli import _resolve

                dtname = (form.get("dt") or [""])[0]
                sk = (form.get("skill") or [""])[0]
                data = _resolve(dtname)
                msg = skillmgr.teach(data["name"], [sk])
                tmux_send.send_keys(data["run"], msg)
            except SystemExit as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/skill-used":
            skillmgr.log_use(
                (form.get("dt") or [""])[0],
                (form.get("name") or [""])[0],
                (form.get("ok") or ["1"])[0] != "0",
                (form.get("detail") or [""])[0],
            )
            self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/model":
            side = (form.get("side") or ["op"])[0]
            model = (form.get("model") or [""])[0]
            which = ["trigger"] if side == "op" else ["bullet"]
            try:
                data = get_control_service().model(name, model, which).data
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            info = data.get("trigger") if side == "op" else data.get("bullet")
            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "model": (info or {}).get("model") or model,
                        "trigger_model": (data.get("trigger") or {}).get("model") or "",
                        "bullet_model": (data.get("bullet") or {}).get("model") or "",
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/freeze":
            sides = []
            side = (form.get("side") or ["both"])[0]
            if side in {"both", "trigger", "op"}:
                sides.append("trigger")
            if side in {"both", "bullet", "run"}:
                sides.append("bullet")
            try:
                data = (
                    get_control_service()
                    .freeze(name, sides, (form.get("tool") or ["auto"])[0])
                    .data
                )
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "dst": oc_ops.is_dst(data),
                        "trigger_model": (data.get("trigger") or {}).get("model") or "",
                        "bullet_model": (data.get("bullet") or {}).get("model") or "",
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        service = get_control_service()
        try:
            if parsed.path == "/api/tunnel/create":
                result = service.create_tunnel(
                    (form.get("name") or [""])[0],
                    server=(form.get("server") or [""])[0],
                    container=(form.get("container") or [""])[0],
                    directory=(form.get("directory") or [""])[0],
                    trigger_tool=(form.get("trigger_tool") or ["opencode"])[0],
                    bullet_tool=(form.get("bullet_tool") or ["opencode"])[0],
                    local=(form.get("local") or ["0"])[0] == "1",
                )
            elif parsed.path == "/api/tunnel/remove":
                result = service.remove_tunnel(
                    name,
                    confirm=(form.get("confirm") or [""])[0],
                    kill=(form.get("kill") or ["0"])[0] == "1",
                )
            elif parsed.path == "/api/tunnel/reconnect":
                result = service.reconnect(name)
            elif parsed.path == "/api/tunnel/drop":
                result = service.drop(name, confirm=(form.get("confirm") or [""])[0])
            elif parsed.path in {"/api/hub/push", "/api/hub/pull"}:
                result = service.hub_sync(parsed.path.rsplit("/", 1)[-1])
            elif parsed.path == "/api/config/switch":
                result = service.switch_mode(
                    mode=(form.get("mode") or [""])[0],
                    client=(form.get("client") or [""])[0],
                    workspace=(form.get("workspace") or [""])[0],
                    server=(form.get("server") or [""])[0],
                    user=(form.get("user") or [""])[0],
                    confirm=(form.get("confirm") or [""])[0],
                )
            elif parsed.path == "/api/health/probe":
                result = service.probe_health(name)
            elif parsed.path == "/api/health/recover":
                result = service.recover(
                    name,
                    force=(form.get("force") or ["0"])[0] == "1",
                    confirm=(form.get("confirm") or [""])[0],
                )
            elif parsed.path == "/api/health/auto":
                result = service.set_auto_recover(
                    name, (form.get("enabled") or ["0"])[0] == "1"
                )
            else:
                result = None
        except ControlError as exc:
            self._send(
                exc.status,
                json.dumps(exc.as_dict()),
                "application/json; charset=utf-8",
            )
            return
        if result is not None:
            self._send(
                200,
                json.dumps(result.as_dict()),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path != "/send":
            self._send(404, "not found")
            return
        side = (form.get("side") or ["op"])[0]
        text = (form.get("text") or [""])[0]
        try:
            result = get_control_service().send(name, text, side)
            pane = result.data["pane"]
        except ControlError as exc:
            self._send(
                exc.status, json.dumps(exc.as_dict()), "application/json; charset=utf-8"
            )
            return
        accept = self.headers.get("Accept") or ""
        if "application/json" in accept or self.headers.get("X-Requested-With"):
            self._send(
                200,
                json.dumps({"ok": True, "pane": pane}),
                "application/json; charset=utf-8",
            )
            return
        self.send_response(303)
        self.send_header("Location", f"/tunnels?t={normalize_dt(name)}")
        self.end_headers()


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        # The URL is already printed; headless and restricted environments may not have a browser.
        pass


def serve(
    host: str = HOST, port: int = DEFAULT_PORT, open_browser: bool = True
) -> None:
    with WebHTTPServer((host, port), Handler) as httpd:
        url = f"http://{host}:{port}"
        print(f"dt web  {url}  (Ctrl-C stop)")
        if open_browser:
            opener = threading.Timer(0.15, _open_browser, args=(url,))
            opener.daemon = True
            opener.start()
        httpd.serve_forever()
