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
                "op_live": tmux_ops.has_session(op) if op else False,
                "run_live": tmux_ops.has_session(run) if run else False,
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


def _page(selected: str, side: str) -> str:
    rows = _tunnels()
    if not selected and rows:
        selected = rows[0]["name"]
    if side not in {"op", "run"}:
        side = "run"
    items = []
    for row in rows:
        cls = "nav-item"
        if row["name"] == selected:
            cls += " active"
        live = "●" if (row["op_live"] or row["run_live"]) else "○"
        dst = "DST" if row["dst"] else "DT"
        items.append(
            f'<a class="{cls}" href="/?t={html.escape(row["name"])}&side={html.escape(side)}">'
            f'<span class="dot">{live}</span> {html.escape(row["name"])} '
            f'<span class="tag">{dst}</span></a>'
        )
    nav = "\n".join(items) or '<div class="empty">no tunnels</div>'
    meta = ""
    out = "(select a tunnel)"
    pane = ""
    if selected:
        try:
            data = load(find_dt(selected))
        except SystemExit:
            data = {}
        pane = _pane_name(data, side)
        if pane and tmux_ops.has_session(pane):
            out = tmux_ops.capture_pane(pane, -120) or "(empty pane)"
        elif pane:
            out = f"(tmux session {pane} not running)"
        trigger = data.get("trigger") or {}
        bullet = data.get("bullet") or {}
        meta = (
            f'{html.escape(selected)} · {html.escape(pane or "—")} · '
            f'op={html.escape((tmux_ops.pane_info(data.get("op") or "").get("cmd") or "—"))} · '
            f'run={html.escape((tmux_ops.pane_info(data.get("run") or "").get("cmd") or "—"))} · '
            f'trigger={html.escape(trigger.get("slug") or "—")} · '
            f'bullet={html.escape(bullet.get("slug") or "—")}'
        )
    op_cls = "tab active" if side == "op" else "tab"
    run_cls = "tab active" if side == "run" else "tab"
    sel = html.escape(selected)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dt web</title>
<style>
:root {{ --bg:#0f1419; --panel:#1a2332; --line:#2a3548; --text:#e7ecf3; --muted:#8b9bb4; --acc:#3d8bfd; --ok:#3dd68c; }}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; height:100%; background:var(--bg); color:var(--text); font:13px/1.45 ui-sans-serif,system-ui,sans-serif; }}
.app {{ display:flex; height:100%; }}
.side {{ width:220px; background:#121a26; border-right:1px solid var(--line); display:flex; flex-direction:column; }}
.brand {{ padding:14px 16px; font-weight:700; letter-spacing:.04em; border-bottom:1px solid var(--line); }}
.brand span {{ color:var(--muted); font-weight:400; }}
.nav {{ flex:1; overflow:auto; padding:8px; }}
.nav-item {{ display:flex; align-items:center; gap:8px; padding:8px 10px; color:var(--text); text-decoration:none; border-radius:6px; margin-bottom:2px; }}
.nav-item:hover {{ background:#1e2a3d; }}
.nav-item.active {{ background:#24344d; }}
.dot {{ font-size:10px; color:var(--ok); width:12px; }}
.tag {{ margin-left:auto; color:var(--muted); font-size:11px; }}
.main {{ flex:1; display:flex; flex-direction:column; min-width:0; }}
.bar {{ display:flex; align-items:center; gap:10px; padding:10px 14px; border-bottom:1px solid var(--line); background:var(--panel); }}
.tab {{ color:var(--muted); text-decoration:none; padding:4px 10px; border-radius:4px; border:1px solid transparent; }}
.tab.active {{ color:var(--text); background:#24344d; border-color:var(--line); }}
.meta {{ color:var(--muted); flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.out {{ flex:1; margin:0; padding:12px 14px; overflow:auto; background:#0b1016; color:#d6e2f0; font:12px/1.4 ui-monospace,Menlo,monospace; white-space:pre-wrap; word-break:break-word; }}
.form {{ display:flex; gap:8px; padding:10px 14px; border-top:1px solid var(--line); background:var(--panel); }}
textarea {{ flex:1; min-height:64px; resize:vertical; background:#0b1016; color:var(--text); border:1px solid var(--line); border-radius:6px; padding:8px; font:12px ui-monospace,Menlo,monospace; }}
button {{ background:var(--acc); color:#fff; border:0; border-radius:6px; padding:0 16px; cursor:pointer; font-weight:600; }}
.empty {{ color:var(--muted); padding:12px; }}
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand">dt web <span>tunnels</span></div>
    <nav class="nav">{nav}</nav>
  </aside>
  <section class="main">
    <div class="bar">
      <a class="{op_cls}" href="/?t={sel}&side=op">op / trigger</a>
      <a class="{run_cls}" href="/?t={sel}&side=run">run / bullet</a>
      <div class="meta">{meta}</div>
    </div>
    <pre class="out" id="out">{html.escape(out)}</pre>
    <form class="form" method="post" action="/send">
      <input type="hidden" name="t" value="{sel}">
      <input type="hidden" name="side" value="{html.escape(side)}">
      <textarea name="text" placeholder="send-keys → {html.escape(pane or "pane")}  (Enter+⌘/Ctrl 用按钮)" required></textarea>
      <button type="submit">Send</button>
    </form>
  </section>
</div>
<script>
const t = {json.dumps(selected)};
const side = {json.dumps(side)};
const out = document.getElementById('out');
async function tick() {{
  if (!t) return;
  const r = await fetch('/api/pane?t=' + encodeURIComponent(t) + '&side=' + encodeURIComponent(side));
  const j = await r.json();
  const next = j.text || '';
  if (next !== out.textContent) {{
    const stick = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
    out.textContent = next;
    if (stick) out.scrollTop = out.scrollHeight;
  }}
}}
setInterval(tick, 1500);
tick();
</script>
</body>
</html>
"""


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
        if parsed.path == "/api/pane":
            name = (qs.get("t") or [""])[0]
            side = (qs.get("side") or ["run"])[0]
            try:
                data = load(find_dt(name))
                pane = _pane_name(data, side)
                text = tmux_ops.capture_pane(pane, -120) if pane and tmux_ops.has_session(pane) else f"(no session {pane})"
                self._send(200, json.dumps({"pane": pane, "text": text}), "application/json; charset=utf-8")
            except SystemExit as exc:
                self._send(404, json.dumps({"error": str(exc)}), "application/json; charset=utf-8")
            return
        if parsed.path in {"/", "/index.html"}:
            selected = (qs.get("t") or [""])[0]
            side = (qs.get("side") or ["run"])[0]
            self._send(200, _page(selected, side))
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
        side = (form.get("side") or ["run"])[0]
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
        self.send_response(303)
        self.send_header("Location", f"/?t={normalize_dt(name)}&side={side}")
        self.end_headers()


def serve(host: str = HOST, port: int = DEFAULT_PORT) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"dt web  http://{host}:{port}  (Ctrl-C stop)")
    httpd.serve_forever()
