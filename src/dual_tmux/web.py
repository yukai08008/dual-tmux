from __future__ import annotations

import html
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import oc as oc_ops
from . import tmux as tmux_ops
from .paneparse import parse_pane, parser_id_for_side
from .config import load_config
from .store import find_dt, iter_dt_files, load, normalize_dt

HOST = "127.0.0.1"
DEFAULT_PORT = 8787


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
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def _pane_name(data: dict, side: str) -> str:
    if side == "op":
        return data.get("op") or ""
    return data.get("run") or ""


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
    sessions = Path(os.environ.get("DT_SESSIONS_HOME", Path.home() / "sessions")).expanduser()
    oc_json = sessions / "opencode" / source / f"{slug}.json" if slug else Path()
    tmux_dir = sessions / "tmux" / source
    last_link = tmux_dir / "last"
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
.mhits {{ position:absolute; left:0; right:0; top:100%; background:#fff; border:1px solid var(--line); border-radius:6px; max-height:220px; overflow:auto; z-index:30; display:none; box-shadow:0 8px 20px rgba(0,0,0,.12); }}
.mhits a {{ display:block; padding:6px 8px; text-decoration:none; color:var(--text); font:12px ui-monospace,Menlo,monospace; }}
.mhits a:hover {{ background:#eff6ff; }}
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
    return (
        f'<a class="{dash}" href="/">Dashboard</a>'
        f'<a class="{tun}" href="/tunnels">隧道</a>'
    )


def dashboard_page() -> str:
    rows = _tunnels()
    live = sum(1 for r in rows if r["op_live"] or r["run_live"])
    dst = sum(1 for r in rows if r["dst"])
    cards = []
    for r in rows:
        live_s = "live" if (r["op_live"] or r["run_live"]) else "down"
        kind = "DST" if r["dst"] else "DT"
        cards.append(
            f'<div class="stat"><b>{html.escape(r["name"])}</b>'
            f'<span>{kind} · {live_s} · op {html.escape(r["op_cmd"] or "—")} · '
            f'run {html.escape(r["run_cmd"] or "—")}</span></div>'
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
    trigger_out = html.escape(_capture(op)) if selected else "选定隧道后显示 trigger（op_*）"
    bullet_out = html.escape(_capture(run)) if selected else "选定隧道后显示 bullet（run_*）"
    meta = ""
    if selected and data:
        meta = (
            f'{html.escape(selected)} · op=<code>{html.escape(op)}</code> · '
            f'run=<code>{html.escape(run)}</code> · '
            f'DST={"yes" if oc_ops.is_dst(data) else "no"}'
        )
    sel = html.escape(selected)
    body = f"""
    <div class="top"><h1>隧道</h1><p>模糊搜索选定 DT，向 trigger 提交，下方轮询 op / run 屏</p></div>
    <div class="content">
      <div class="card pick">
        <label>选择隧道（dt ls）</label>
        <input id="q" type="search" placeholder="输入名称模糊搜索…" value="{sel}" autocomplete="off">
        <div class="hits" id="hits"></div>
        <div class="meta" id="meta" style="margin-top:8px">{meta}</div>
        <div class="btabs" id="btabs" style="margin-top:12px"></div>
        <div class="models" id="models">
          <div class="field"><label>trigger 模型</label><input id="m-op" placeholder="模糊搜索 provider/id" autocomplete="off"><div class="mhits" id="mh-op"></div></div>
          <div class="field"><label>bullet 模型</label><input id="m-run" placeholder="模糊搜索 provider/id" autocomplete="off"><div class="mhits" id="mh-run"></div></div>
          <button type="button" id="btn-model-op">切换 trigger</button>
          <button type="button" id="btn-model-run">切换 bullet</button>
          <button type="button" class="ghost" id="btn-freeze">Freeze</button>
        </div>
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
        <h2>trigger 问答</h2>
        <div class="thread" id="thread"></div>
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
      <div class="card">
        <h2>会话同步</h2>
        <div class="sync" id="syncbox">选定隧道后显示 op / run 名称与 persist 时间</div>
      </div>
    </div>
<script>
const rows = {names};
const hits = document.getElementById('hits');
const q = document.getElementById('q');
const tname = document.getElementById('tname');
const meta = document.getElementById('meta');
const logEl = document.getElementById('log');
const box = document.getElementById('box');
const opout = document.getElementById('opout');
const runout = document.getElementById('runout');
const oplabel = document.getElementById('oplabel');
const runlabel = document.getElementById('runlabel');
const sendf = document.getElementById('sendf');
const lampOp = document.getElementById('lamp-op');
const lampRun = document.getElementById('lamp-run');
const threadEl = document.getElementById('thread');
let chosen = {json.dumps(selected)};
const LOG_MAX = 200;
const THREAD_MAX = 40;
let tabSeq = 1;
const tabs = [];
let activeTab = null;

function emptyState(name) {{
  return {{
    id: tabSeq++,
    name: name || '',
    lastOp: '', lastRun: '', lastSent: 0, waiting: false, pollQuiet: 0,
    opAtSend: '', lastAsk: '', lastPollKey: '',
    finalOp: 'gray', finalRun: 'gray',
    thread: [], log: [],
  }};
}}
function colorOf(st) {{
  if (!st || !st.name) return 'gray';
  if (st.waiting) return 'yellow';
  if (st.finalOp === 'red' || st.finalRun === 'red') return 'red';
  if (st.finalOp === 'green' || st.finalRun === 'green') return 'green';
  return 'gray';
}}
function renderTabs() {{
  const el = document.getElementById('btabs');
  el.innerHTML = tabs.map(st => {{
    const on = st === activeTab ? ' active' : '';
    const c = colorOf(st);
    const label = st.name || '未选隧道';
    return '<div class="btab '+c+on+'" data-id="'+st.id+'"><i class="dot"></i><span>'+label+'</span><button class="x" data-close="'+st.id+'" type="button">×</button></div>';
  }}).join('') + '<button class="btab-add" id="tabadd" type="button">+</button>';
}}
function applyState(st) {{
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
  }} else {{
    mop.value = '';
    mrun.value = '';
    oplabel.textContent = 'op_*';
    runlabel.textContent = 'run_*';
    meta.textContent = st.name ? st.name : '未选隧道';
  }}
  setLamp(lampOp, st.waiting ? 'yellow' : st.finalOp);
  setLamp(lampRun, st.waiting ? 'yellow' : st.finalRun);
  setPollBusy(st.waiting);
  threadEl.innerHTML = '';
  (st.thread || []).forEach(item => addBubble(item.kind, item.text, item.extra, true));
  logEl.innerHTML = '';
  (st.log || []).forEach(item => logLine(item.kind, item.text, true));
  history.replaceState(null, '', st.name ? ('/tunnels?t='+encodeURIComponent(st.name)) : '/tunnels');
}}
function activate(st) {{
  activeTab = st;
  renderTabs();
  applyState(st);
  if (st.name) tick();
}}
function addTab(name) {{
  const st = emptyState(name || '');
  tabs.push(st);
  activate(st);
  return st;
}}
function closeTab(id) {{
  const i = tabs.findIndex(t => t.id === id);
  if (i < 0) return;
  const was = tabs[i] === activeTab;
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
function addBubble(kind, text, extra, skipSave) {{
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
  const bits = [];
  if (extra.model) bits.push(extra.model);
  if (extra.elapsed) bits.push(extra.elapsed);
  bits.push(new Date().toLocaleTimeString());
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = bits.join(' · ');
  b.appendChild(meta);
  threadEl.appendChild(b);
  while (threadEl.children.length > THREAD_MAX) threadEl.removeChild(threadEl.firstChild);
  threadEl.scrollTop = threadEl.scrollHeight;
  if (!skipSave && activeTab) {{
    activeTab.thread = activeTab.thread || [];
    activeTab.thread.push({{kind, text, extra: extra || {{}}}});
    if (activeTab.thread.length > THREAD_MAX) activeTab.thread.shift();
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
  }}
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
function pick(name) {{
  const row = rows.find(r => r.name === name);
  if (!row) return;
  hits.style.display = 'none';
  if (!activeTab) addTab(name);
  const st = activeTab;
  st.name = name;
  st.lastOp = st.lastRun = '';
  st.waiting = false;
  st.pollQuiet = 0;
  st.opAtSend = '';
  st.lastAsk = '';
  st.lastPollKey = '';
  st.finalOp = 'gray';
  st.finalRun = 'gray';
  activate(st);
  logLine('pick', '已选定 ' + name + ' · ' + row.op + ' / ' + row.run);
}}
q.addEventListener('focus', renderHits);
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
function renderSync(s) {{
  if (!s) return;
  const el = document.getElementById('syncbox');
  const marks = [];
  function line(k, v, prev) {{
    const chg = prev && v && prev !== v ? '<span class="chg">更新</span>' : '';
    marks.push('<div class="row"><span class="k">'+k+'</span><span class="v">'+(v || '—')+' '+chg+'</span></div>');
  }}
  line('op 会话', s.op + (s.op_live ? ' · live' : ' · down'), lastSync.op);
  line('run 会话', s.run + (s.run_live ? ' · live' : ' · down'), lastSync.run);
  line('oc slug', s.oc_slug, lastSync.oc_slug);
  line('oc 快照', s.oc_mtime, lastSync.oc_mtime);
  line('tmux last', s.tmux_last, lastSync.tmux_last);
  line('来源', s.source, lastSync.source);
  el.innerHTML = marks.join('');
  lastSync = s;
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
  snap(opout, j.op_text || '');
  snap(runout, j.run_text || '');
  if (j.sync) renderSync(j.sync);
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
    if (opChanged) {{
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
        st.lastPollKey = '';
        renderTabs();
      }}
    }}
  }} else {{
    setPollBusy(false);
    setLamp(lampOp, st.finalOp);
    setLamp(lampRun, st.finalRun);
    if (opChanged || runChanged) {{
      logLine('poll', (opChanged ? 'trigger 更新' : 'bullet 更新') + ' · op=' + opState + ' run=' + runState);
    }}
  }}
  renderTabs();
}}
setInterval(tick, 1500);

document.getElementById('btabs').addEventListener('click', (e) => {{
  const close = e.target.closest('[data-close]');
  if (close) {{ e.stopPropagation(); closeTab(Number(close.dataset.close)); return; }}
  if (e.target.closest('#tabadd')) {{ addTab(''); return; }}
  const tab = e.target.closest('.btab');
  if (!tab) return;
  const st = tabs.find(t => t.id === Number(tab.dataset.id));
  if (st) activate(st);
}});
sendf.addEventListener('submit', async (e) => {{
  e.preventDefault();
  const st = activeTab;
  if (!st || !st.name || !box.value.trim()) return;
  st.lastAsk = box.value.trim();
  const preview = st.lastAsk.replace(/\\s+/g, ' ').slice(0, 80);
  addBubble('ask', st.lastAsk);
  logLine('send', preview || '(empty)');
  st.opAtSend = st.lastOp;
  st.waiting = true;
  st.pollQuiet = 0;
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
document.getElementById('btn-freeze').addEventListener('click', async () => {{
  const st = activeTab;
  if (!st || !st.name) return;
  logLine('send', 'freeze ' + st.name);
  try {{
    const j = await postForm('/api/freeze', {{ t: st.name }});
    syncRowModels(j);
    const row = rows.find(r => r.name === st.name);
    if (row) row.dst = !!j.dst;
    logLine('done', 'freeze 完成 · DST=' + (j.dst ? 'yes' : 'no'));
    applyState(st);
  }} catch (err) {{ logLine('err', String(err.message || err)); }}
}});
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
addTab({json.dumps(selected)});
</script>
    """
    return _shell(_nav("tunnels"), body, "dt web · 隧道")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: str | bytes, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/tunnels":
            self._send(200, json.dumps(_tunnels()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/tunnel":
            name = (qs.get("t") or [""])[0]
            try:
                data = load(find_dt(name))
            except SystemExit as exc:
                self._send(404, json.dumps({"error": str(exc)}), "application/json; charset=utf-8")
                return
            op = data.get("op") or ""
            run = data.get("run") or ""
            payload = {
                "name": data.get("name"),
                "op": op,
                "run": run,
                "dst": oc_ops.is_dst(data),
                "op_live": bool(op) and tmux_ops.has_session(op),
                "run_live": bool(run) and tmux_ops.has_session(run),
                "op_cmd": tmux_ops.pane_info(op).get("cmd") if op else "",
                "run_cmd": tmux_ops.pane_info(run).get("cmd") if run else "",
                "op_text": _capture(op),
                "run_text": _capture(run),
                "op_parsed": parse_pane(_capture(op), parser_id_for_side(data.get("trigger"))).as_dict(),
                "run_parsed": parse_pane(_capture(run), parser_id_for_side(data.get("bullet"))).as_dict(),
                "trigger_model": (data.get("trigger") or {}).get("model") or "",
                "bullet_model": (data.get("bullet") or {}).get("model") or "",
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
        self._send(404, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw)
        name = (form.get("t") or [""])[0]
        if parsed.path == "/api/model":
            side = (form.get("side") or ["op"])[0]
            model = (form.get("model") or [""])[0]
            which = ["trigger"] if side == "op" else ["bullet"]
            try:
                from .cli import apply_model

                data = apply_model(name, model, which)
            except SystemExit as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
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
            try:
                from .cli import apply_freeze

                data = apply_freeze(name)
            except SystemExit as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
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
        if parsed.path != "/send":
            self._send(404, "not found")
            return
        side = (form.get("side") or ["op"])[0]
        text = (form.get("text") or [""])[0]
        try:
            data = load(find_dt(name))
            pane = _pane_name(data, side)
            if not pane:
                raise SystemExit("[err] no pane")
            tmux_ops.send_keys(pane, text)
        except SystemExit as exc:
            self._send(400, str(exc), "text/plain; charset=utf-8")
            return
        accept = self.headers.get("Accept") or ""
        if "application/json" in accept or self.headers.get("X-Requested-With"):
            self._send(200, json.dumps({"ok": True, "pane": pane}), "application/json; charset=utf-8")
            return
        self.send_response(303)
        self.send_header("Location", f"/tunnels?t={normalize_dt(name)}")
        self.end_headers()


def serve(host: str = HOST, port: int = DEFAULT_PORT) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"dt web  http://{host}:{port}  (Ctrl-C stop)")
    httpd.serve_forever()
