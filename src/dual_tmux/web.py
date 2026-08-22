from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import oc as oc_ops
from . import tmux as tmux_ops
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
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def _pane_name(data: dict, side: str) -> str:
    if side == "op":
        return data.get("op") or ""
    return data.get("run") or ""


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
      </div>
      <div class="card">
        <h2>发给 trigger（op_*）</h2>
        <form id="sendf">
          <input type="hidden" name="t" id="tname" value="{sel}">
          <textarea name="text" id="box" rows="10" placeholder="提交后 send-keys 到 trigger pane" {"disabled" if not selected else ""}></textarea>
          <div style="margin-top:8px"><button type="submit" {"disabled" if not selected else ""}>提交</button></div>
        </form>
      </div>
      <div class="card">
        <h2>轮询状态</h2>
        <div class="log" id="log"></div>
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
let chosen = {json.dumps(selected)};
let lastOp = '', lastRun = '';
let lastSent = 0;
let waiting = false;
let pollQuiet = 0;
const LOG_MAX = 200;

function logLine(kind, text) {{
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
}}
if (chosen) logLine('pick', '已选定 ' + chosen);
else logLine('idle', '先选定隧道');

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
  chosen = name;
  tname.value = name;
  q.value = name;
  hits.style.display = 'none';
  box.disabled = false;
  sendf.querySelector('button').disabled = false;
  oplabel.textContent = row.op;
  runlabel.textContent = row.run;
  meta.innerHTML = name+' · op=<code>'+row.op+'</code> · run=<code>'+row.run+'</code> · DST='+(row.dst?'yes':'no');
  history.replaceState(null, '', '/tunnels?t='+encodeURIComponent(name));
  lastOp = lastRun = '';
  waiting = false;
  pollQuiet = 0;
  logLine('pick', '已选定 ' + name + ' · ' + row.op + ' / ' + row.run);
  tick();
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

function snap(el, next) {{
  if (next === el.textContent) return;
  const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  el.textContent = next;
  if (stick) el.scrollTop = el.scrollHeight;
}}

async function tick() {{
  if (!chosen) return;
  const r = await fetch('/api/tunnel?t=' + encodeURIComponent(chosen));
  const j = await r.json();
  if (j.error) {{ logLine('err', j.error); return; }}
  snap(opout, j.op_text || '');
  snap(runout, j.run_text || '');
  const opChanged = j.op_text !== lastOp;
  const runChanged = j.run_text !== lastRun;
  lastOp = j.op_text || '';
  lastRun = j.run_text || '';
  const opState = j.op_live ? (j.op_cmd || 'live') : 'down';
  const runState = j.run_live ? (j.run_cmd || 'live') : 'down';
  if (waiting) {{
    if (opChanged) {{
      const tail = (j.op_text || '').trim().split('\\n').filter(Boolean).slice(-1)[0] || 'trigger 有输出';
      logLine('poll', tail.slice(0, 120));
      pollQuiet = 0;
    }} else {{
      pollQuiet += 1;
      if (pollQuiet === 1) logLine('poll', '等待 trigger · op=' + opState + ' run=' + runState);
      if (pollQuiet >= 8) {{
        logLine('done', '本轮轮询结束 · op=' + opState + ' run=' + runState);
        waiting = false;
        pollQuiet = 0;
      }}
    }}
  }} else if (opChanged || runChanged) {{
    logLine('poll', (opChanged ? 'trigger 更新' : 'bullet 更新') + ' · op=' + opState + ' run=' + runState);
  }}
}}
setInterval(tick, 1500);
if (chosen) tick();

sendf.addEventListener('submit', async (e) => {{
  e.preventDefault();
  if (!chosen || !box.value.trim()) return;
  const preview = box.value.trim().replace(/\\s+/g, ' ').slice(0, 80);
  logLine('send', preview || '(empty)');
  const body = new URLSearchParams({{ t: chosen, side: 'op', text: box.value }});
  const r = await fetch('/send', {{ method: 'POST', headers: {{ 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' }}, body }});
  if (!r.ok) {{ logLine('err', await r.text()); return; }}
  lastSent = Date.now();
  waiting = true;
  pollQuiet = 0;
  box.value = '';
  logLine('send', '已提交到 trigger，开始轮询');
  tick();
}});
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
            }
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
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
        if parsed.path != "/send":
            self._send(404, "not found")
            return
        name = (form.get("t") or [""])[0]
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
