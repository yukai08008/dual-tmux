from __future__ import annotations

import html
import json

from . import oc as oc_ops
from .control import ControlError, get_control_service


def _tunnels() -> list[dict]:
    from .web import _tunnels as get_tunnels

    return get_tunnels()


def _capture(name: str) -> str:
    from .web import _capture as capture

    return capture(name)


def _shell(nav: str, body: str, title: str) -> str:
    from .web_ui import get_components_css, get_components_js, get_theme_css

    theme_css = get_theme_css()
    comp_css = get_components_css()
    comp_js = get_components_js()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%232563eb'/%3E%3Cpath d='M15 18h34v8H36v24h-8V26H15z' fill='white'/%3E%3C/svg%3E">
<style>
{theme_css}
{comp_css}
</style>
<script>
{comp_js}
</script>
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
.ownership {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:10px; }}
.own-block {{ border:1px solid var(--line); border-radius:7px; padding:10px; background:#f8fafc; min-width:0; }}
.own-block h3 {{ margin:0 0 7px; font-size:12px; }}
.own-line {{ display:flex; gap:8px; padding:3px 0; align-items:flex-start; }}
.own-line .k {{ color:var(--muted); flex:0 0 82px; }}
.own-line .v {{ min-width:0; overflow-wrap:anywhere; font-family:ui-monospace,Menlo,monospace; }}
.own-good {{ color:var(--ok); }} .own-bad {{ color:#dc2626; }} .own-warn {{ color:#b45309; }}
.takeover-actions {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; align-items:center; }}
.takeover-actions .danger {{ background:#dc2626; }}
.takeover-actions button:disabled {{ opacity:.45; cursor:not-allowed; }}
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
.banner {{ padding:10px 14px; border-radius:6px; margin-top:10px; font-size:12px; line-height:1.5; }}
.banner-warn {{ background:#fef3c7; border:1px solid #fde68a; color:#92400e; }}
.banner-ok {{ background:#ecfdf5; border:1px solid #a7f3d0; color:#065f46; }}
.badge {{ display:inline-block; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:700; text-transform:uppercase; }}
.badge-dst {{ background:#d1fae5; color:#047857; }}
.badge-draft {{ background:#fef3c7; color:#b45309; }}
.pane-toolbar {{ display:flex; justify-content:space-between; align-items:center; margin-top:14px; margin-bottom:8px; }}
.pane-view-tabs {{ display:inline-flex; align-items:center; gap:6px; }}
.toolbar-label {{ font-size:12px; font-weight:600; color:var(--muted); }}
.btn-layout {{ background:var(--card); border:1px solid var(--line); color:var(--text); padding:4px 10px; border-radius:5px; font-size:12px; cursor:pointer; }}
.btn-layout:hover {{ background:#f3f4f6; }}
.btn-layout.active {{ background:var(--acc); color:#fff; border-color:var(--acc); }}
.panes-container.view-split {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
@media (max-width: 900px) {{ .panes-container.view-split {{ grid-template-columns:1fr; }} }}
.panes-container.view-op #card-run {{ display:none; }}
.panes-container.view-run #card-op {{ display:none; }}
.panes-container.view-op, .panes-container.view-run {{ display:block; }}
.pane-card {{ margin-top:0 !important; }}

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
        <div class="stat"><b id="fs-owner">—</b><span>WS owner</span></div>
        <div class="stat"><b id="fs-generation">—</b><span>Generation</span></div>
      </div>
      <div class="card">
        <h2>扫码绑定</h2>
        <p>不需要 App ID、App Secret 或公网 callback。飞书确认后会自动创建 PersonalAgent，凭据只以加密形式保存在服务端。</p>
        <div class="models"><button id="fs-pair">生成一次性二维码</button><button class="ghost" id="fs-unbind">解绑机器人</button></div>
        <div id="fs-pair-box" style="display:none;margin-top:12px"><img id="fs-qr" alt="飞书绑定二维码" width="260" height="260"><p><a id="fs-url" target="_blank" rel="noopener">在飞书授权页打开</a></p><p class="meta" id="fs-expiry"></p></div>
        <pre class="out" id="fs-result" style="height:180px">等待操作</pre>
      </div>
      <div class="card"><h2>已绑定身份</h2><div id="fs-bindings" class="log" style="height:220px"></div></div>
    </div>
    <script>
    const out=document.getElementById('fs-result');
    async function api(url,body){const r=await fetch(url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw new Error((j.error&&j.error.message)||JSON.stringify(j));return j}
    async function refresh(){try{const s=await api('/api/feishu/status');const d=s.daemon||{};document.getElementById('fs-configured').textContent=s.installed?'ready':(s.registration_status||'idle');document.getElementById('fs-bound').textContent=(s.bindings||[]).length;document.getElementById('fs-ws').textContent=d.connector||'stopped';document.getElementById('fs-owner').textContent=d.owner||'none';document.getElementById('fs-generation').textContent=d.generation||'—';document.getElementById('fs-pair').disabled=!!s.installed;document.getElementById('fs-bindings').innerHTML=(s.bindings||[]).map(x=>'<div class="row"><span class="tag done">bound</span><span class="msg">'+Object.entries(x).filter(([k,v])=>v).map(([k,v])=>k+'='+v).join(' · ')+'</span></div>').join('')||'尚未绑定';if((d.candidates||[]).length)out.dataset.candidates=JSON.stringify(d.candidates);if(s.registration_status==='pending'){const p=await api('/api/feishu/poll',{});if(p.status==='installed'){out.textContent='绑定成功；dt daemon 将自动启动 WebSocket。';document.getElementById('fs-pair-box').style.display='none';}}}catch(e){out.textContent=e.message}}
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
            (
                "dt config --init --local --client tm_laptop\n"
                "# 以后接入或更换 Hub\n"
                "dt config --server myserver --user andy\n"
                "dt doctor"
            ),
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
            from datanode.adapters import to_legacy_tunnel

            node = get_control_service().get_tunnel_node(selected)
            data = to_legacy_tunnel(node)
        except (ControlError, KeyError, SystemExit):
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
        <div id="dst-banner" class="banner" style="display:none"></div>
        <div class="btabs" id="btabs" style="margin-top:12px"></div>
        <div class="recent" id="recent" style="margin-top:8px"></div>
        <div class="sync" id="syncbox" style="margin-top:10px">选定隧道后显示会话同步</div>
        <div class="sync" id="clientbox" style="margin-top:8px">
          <span id="client-op">trigger client —</span> · <span id="client-run">bullet client —</span>
        </div>
        <div class="sync" id="healthbox" style="margin-top:8px">health —</div>
        <div class="card" style="margin-top:10px">
          <h2>占用与接管</h2>
          <div id="ownershipbox" class="ownership"><div class="own-block">等待 daemon/tick 采集状态…</div></div>
          <div class="takeover-actions">
            <button type="button" class="ghost" id="btn-plan">刷新预检</button>
            <button type="button" class="ghost" id="btn-handoff" disabled>接管</button>
            <button type="button" id="btn-resume" disabled>执行安全 Resume</button>
            <button type="button" class="danger" id="btn-force-resume" disabled>高风险 Force Resume</button>
          </div>
          <div class="meta" id="ownershiphint" style="margin-top:8px">页面读取后台缓存；刷新不会探测 SSH，也不会启动会话。</div>
        </div>
        <div class="models" id="lifecycle">
          <div class="field"><label>freeze 范围</label><select id="freeze-side"><option value="both">trigger + bullet</option><option value="trigger">trigger</option><option value="bullet">bullet</option></select></div>
          <div class="field"><label>远端客户端</label><select id="freeze-tool"><option value="auto">自动识别</option><option value="opencode">OpenCode</option><option value="codex">Codex</option><option value="claude">Claude Code</option></select></div>
          <button type="button" class="ghost" id="btn-freeze">Freeze</button>
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
      <div id="command-sender-wrap" style="margin-top:12px;"></div>
      <!-- 隐藏兼容节点 -->
      <form id="sendf" style="display:none;">
        <input type="hidden" name="t" id="tname" value="{sel}">
        <textarea name="text" id="box"></textarea>
        <button type="submit"></button>
        <span id="lamp-op" class="lamp gray"></span>
        <span id="lamp-run" class="lamp gray"></span>
      </form>
      <div class="card">
        <div class="h2row pollhead idle" id="pollhead">
          <h2>轮询状态</h2>
          <i class="spin" id="pollspin"></i>
        </div>
        <div class="log idle" id="log"></div>
      </div>
      <div id="dual-terminal-wrap" style="margin-top:12px;"></div>
      <div class="dt-page-footer" style="padding: 28px 0 72px 0; display: flex; align-items: center; justify-content: center; color: var(--dt-text-muted); font-size: 12px;">
        <span>· dual-tmux 会话视窗到底 · 已预留底部操作空白 ·</span>
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
const ownershipBox = document.getElementById('ownershipbox');
const ownershipHint = document.getElementById('ownershiphint');
const logEl = document.getElementById('log');
const box = document.getElementById('box');
window.terminal = new DualTerminalComponent({{
  container: document.getElementById('dual-terminal-wrap'),
}});
window.terminal.render();
window.terminal.updatePane('op', {{
  name: {json.dumps(op or "op_*")},
  text: {json.dumps(trigger_out if selected else "选定隧道后显示 Trigger 会话...")},
  live: false,
}});
window.terminal.updatePane('run', {{
  name: {json.dumps(run or "run_*")},
  text: {json.dumps(bullet_out if selected else "选定隧道后显示 Bullet 会话...")},
  live: false,
}});

window.commandSender = new CommandSenderComponent({{
  container: document.getElementById('command-sender-wrap'),
  target: 'op',
  onSend: async ({{ target, text }}) => {{
    await handleSend(target, text);
  }},
  onInterrupt: async ({{ target, kind }}) => {{
    await handleInterrupt(target, kind);
  }},
}});
window.commandSender.render();
if (!{json.dumps(selected)}) {{
  window.commandSender.setDisabled(true);
}}
const opout = document.getElementById('dt-screen-op');
const runout = document.getElementById('dt-screen-run');
const oplabel = document.getElementById('dt-title-op');
const runlabel = document.getElementById('dt-title-run');
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
    pending: null,
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
  st.lastCompletion=item.lastCompletion||'';
  st.pending=item.pending&&item.pending.id?{{...item.pending}}:null;
  st.waiting=!!st.pending;
  st.waitStartedAt=st.pending?Date.parse(st.pending.startedAt||'')||Date.now():0;
  st.completionAtSend=st.pending?st.pending.baselineCompletion||'':'';
  st.lastProgressAt=st.waiting?Date.now():0;
  st.lastMeaningfulKey='';
  st.longWarned=st.stallWarned=st.attentionWarned=false;
  st.thread=Array.isArray(item.thread)?item.thread.slice(-THREAD_MAX):[];
  st.log=Array.isArray(item.log)?item.log.slice(-LOG_MAX):[];
  return st;
}}
function statePayload() {{
  tabs.filter(st=>st.name).forEach(st => {{
    const item=historyState(st.name);
    item.finalOp=st.finalOp||'gray'; item.finalRun=st.finalRun||'gray';
    item.lastCompletion=st.lastCompletion||'';
    item.pending=st.pending?{{...st.pending}}:null;
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
async function persistTabsNow() {{
  clearTimeout(saveTimer);
  const payload=statePayload(), raw=JSON.stringify(payload);
  try {{ localStorage.setItem(TABS_KEY,raw); }} catch (_) {{}}
  const r=await fetch('/api/web-state',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:raw}});
  if (!r.ok) throw new Error('无法持久化 Web turn 状态');
  lastServerState=raw;
  return payload;
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
  if (window.commandSender) {{
    window.commandSender.setDisabled(!st.name);
  }}
  const row = rows.find(r => r.name === st.name);
  const mop = document.getElementById('m-op');
  const mrun = document.getElementById('m-run');
  if (row) {{
    oplabel.textContent = row.op;
    runlabel.textContent = row.run;
    if (window.terminal) {{
      window.terminal.updatePane('op', {{ name: row.op, live: !!row.op_live }});
      window.terminal.updatePane('run', {{ name: row.run, live: !!row.run_live }});
    }}
    mop.value = row.trigger_model || '';
    mrun.value = row.bullet_model || '';
    meta.innerHTML = st.name+' · op=<code>'+row.op+'</code> · run=<code>'+row.run+'</code> · DST='+(row.dst?'yes':'no');
    const dstBanner = document.getElementById('dst-banner');
    if (dstBanner) {{
      if (row.dst) {{
        dstBanner.style.display = 'block';
        dstBanner.className = 'banner banner-ok';
        dstBanner.innerHTML = '✅ <b>已固化 DST 隧道</b> · 已绑定 trigger 与 bullet 会话对，支持独热占有与跨机安全续接。';
      }} else {{
        dstBanner.style.display = 'block';
        dstBanner.className = 'banner banner-warn';
        dstBanner.innerHTML = '💡 <b>未冻结草稿隧道</b>：当前隧道尚未通过 <code>dt freeze</code> 固化为 DST。请先在终端使用 <code>dt work</code> 或 <code>dt enter</code> 验证会话就绪后执行 <code>dt freeze</code>。未冻结状态禁止执行跨机 Resume 接管。';
      }}
    }}
    const cv=c=>c&&c.name?(c.name+(c.version?' '+c.version:'')+' · '+(c.location||'unknown')):'—';
    clientOp.textContent='trigger client '+cv(row.trigger_client);
    clientRun.textContent='bullet client '+cv(row.bullet_client);
    const hs=(row.health&&row.health.status)||'disabled';
    const he=(row.health&&row.health.last_error)||'—';
    healthBox.textContent='health '+hs+' · auto '+(row.auto_recover?'on':'off')+' · '+he;
  }} else {{
    mop.value = '';
    mrun.value = '';
    const dstBanner = document.getElementById('dst-banner');
    if (dstBanner) dstBanner.style.display = 'none';
    oplabel.textContent = 'op_*';
    runlabel.textContent = 'run_*';
    if (window.terminal) {{
      window.terminal.updatePane('op', {{ name: 'op_*', live: false, text: '选定隧道后显示 Trigger 会话...' }});
      window.terminal.updatePane('run', {{ name: 'run_*', live: false, text: '选定隧道后显示 Bullet 会话...' }});
    }}
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
  if (st.name) {{ tick(); refreshOwnership(st); }}
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

function reconcileLegacyTimeout(st, j) {{
  if (!st || st.waiting || st.finalOp !== 'red' || !j.op_live) return false;
  const thread=st.thread||[], last=thread[thread.length-1];
  const log=st.log||[];
  let timeoutAt=-1;
  log.forEach((item,i)=>{{if(String(item.text||'').includes('停止轮询 · 已等待 90 秒')) timeoutAt=i;}});
  const sentAfter=timeoutAt>=0&&log.slice(timeoutAt+1).some(item=>item.kind==='send');
  const parsed=j.op_parsed||{{}};
  if (timeoutAt<0 || sentAfter || !last || last.kind !== 'fail' || !parsed.body || !parsed.elapsed) return false;
  last.kind='ans';
  last.text=parsed.body;
  last.extra={{...parsed,ts:(last.extra&&last.extra.ts)||new Date().toISOString()}};
  st.finalOp='green';
  st.finalRun=j.run_live?'green':'red';
  st.log.push({{kind:'done',text:'已纠正旧版 90 秒误判 · 本轮实际完成 · '+parsed.elapsed}});
  return true;
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
    const kindBadge = r.dst ? '<span class="badge badge-dst">DST</span>' : '<span class="badge badge-draft">草稿</span>';
    const live = (r.op_live || r.run_live) ? 'live' : 'down';
    return '<a href="#" data-name="'+r.name+'"><b>'+r.name+'</b> <span class="sub">'+kindBadge+' · '+live+' · '+r.op+' / '+r.run+'</span></a>';
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
  st.lastCompletion=prior.lastCompletion||'';
  st.pending=prior.pending&&prior.pending.id?{{...prior.pending}}:null;
  st.waiting=!!st.pending;
  st.waitStartedAt=st.pending?Date.parse(st.pending.startedAt||'')||Date.now():0;
  st.completionAtSend=st.pending?st.pending.baselineCompletion||'':'';
  st.lastProgressAt=st.waiting?Date.now():0;
  st.longWarned=st.stallWarned=st.attentionWarned=false;
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
const reasonText = {{
  already_owned:'当前 Client 已占用，可恢复', free:'当前无人占用，可安全 claim', expired:'占用空闲，可安全 claim',
  occupancy_steal:'其他 Client 占用，Resume 将声明本机占用',
  foreign_idle_detached:'其他 Client 占用，Resume 将声明本机占用',
  ownership_cache_missing:'尚无占用缓存；请确认 dt daemon 正在运行或执行 dt tick',
  ownership_cache_stale:'占用缓存已过期；禁止依据旧证据接管', owner_evidence_stale:'占用证据已过期',
  not_a_frozen_dst:'尚未固化为 DST（请先在终端运行 dt work 验证并执行 dt freeze）',
  trigger_writer_probe_failed:'trigger writer 探测未知，禁止接管', bullet_writer_probe_failed:'bullet writer 探测未知，禁止接管',
  trigger_duplicate_writer:'trigger 存在重复 writer，禁止接管', bullet_duplicate_writer:'bullet 存在重复 writer，禁止接管',
  trigger_native_snapshot_conflict:'trigger native snapshot 冲突，禁止接管', bullet_native_snapshot_conflict:'bullet native snapshot 冲突，禁止接管'
}};
function ownValue(value) {{
  if (value === null || value === undefined || value === '') return '—';
  if (value === true) return 'yes'; if (value === false) return 'no';
  return String(value);
}}
function ownLine(key,value,klass='') {{ return '<div class="own-line"><span class="k">'+esc(key)+'</span><span class="v '+klass+'">'+esc(ownValue(value))+'</span></div>'; }}
function renderOwnership(plan) {{
  const facts=plan.ownership||null, cache=plan.cache||{{}};
  const safe=!!plan.safe, reason=plan.reason||'facts_unavailable';
  ownershipHint.textContent=(reasonText[reason]||reason)+' · cache '+ownValue(cache.freshness)+' · age '+ownValue(cache.age_seconds)+'s';
  document.getElementById('btn-resume').disabled=!safe;
  document.getElementById('btn-force-resume').disabled=!(safe&&plan.action==='claim');
  document.getElementById('btn-handoff').disabled=!(safe&&(plan.action==='claim'||plan.action==='resume'));
  if (!facts) {{
    ownershipBox.innerHTML='<div class="own-block">'+ownLine('预检','STOP','own-bad')+ownLine('原因',reasonText[reason]||reason)+ownLine('缓存',cache.freshness||'missing')+'</div>';
    return;
  }}
  const occ=facts.occupancy||facts.lease||{{}}, writers=facts.writers||{{}}, native=facts.native_snapshots||{{}}, snap=facts.snapshot||{{}};
  const local=occ.state==='local'||occ.source==='local';
  const occTitle=local?'本地单机（无 Hub 占用）':'占用';
  let blocks='<div class="own-block"><h3>'+occTitle+'</h3>'+ownLine('state',occ.state)+ownLine('holder',occ.holder)+ownLine('generation',occ.generation)+ownLine('mine',occ.mine)+ownLine('evidence',snap.freshness)+'</div>';
  ['trigger','bullet'].forEach(role=>{{
    const writer=writers[role]||{{}}, ns=native[role]||{{}};
    const bad=writer.status==='duplicate'||writer.status==='unknown';
    blocks+='<div class="own-block"><h3>'+role+'</h3>'+ownLine('runtime',(facts.runtime||{{}})[role])+ownLine('attached',(facts.attached||{{}})[role])+ownLine('progress',(facts.progress||{{}})[role])+ownLine('writer',ownValue(writer.status)+' · count '+ownValue(writer.count),bad?'own-bad':'own-good')+ownLine('PIDs',(writer.pids||[]).join(', ')||'—')+ownLine('snapshot',ownValue(ns.status)+' · '+ownValue(ns.tool))+ownLine('session',ns.session_id||'—')+'</div>';
  }});
  blocks+='<div class="own-block"><h3>接管结论</h3>'+ownLine('safe',safe,safe?'own-good':'own-bad')+ownLine('action',plan.action)+ownLine('reason',reasonText[reason]||reason)+ownLine('steps',(plan.steps||[]).join(' → ')||'stop')+'</div>';
  ownershipBox.innerHTML=blocks;
}}
async function refreshOwnership(st=activeTab) {{
  if(!st||!st.name) return;
  const expected=st.name;
  try {{
    const r=await fetch('/api/resume/plan?t='+encodeURIComponent(expected));
    const payload=await r.json();
    if(activeTab!==st||st.name!==expected) return;
    if(!r.ok) throw new Error((payload.error&&payload.error.message)||'预检失败');
    renderOwnership(payload.data||payload);
  }} catch(err) {{
    ownershipHint.textContent='Ownership 读取失败 · '+String(err.message||err);
    document.getElementById('btn-resume').disabled=true;
    document.getElementById('btn-force-resume').disabled=true;
    document.getElementById('btn-handoff').disabled=true;
  }}
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
  }}
  if (window.terminal) {{
    window.terminal.updatePane('op', {{
      name: oplabel ? oplabel.textContent : (st.op || 'op_*'),
      cmd: j.op_cmd || '',
      live: !!j.op_live,
      text: j.op_text || '',
    }});
    window.terminal.updatePane('run', {{
      name: runlabel ? runlabel.textContent : (st.run || 'run_*'),
      cmd: j.run_cmd || '',
      live: !!j.run_live,
      text: j.run_text || '',
    }});
  }} else {{
    snap(opout, j.op_text || '');
    snap(runout, j.run_text || '');
  }}
  const lampOpPane = document.getElementById('lamp-op-pane');
  const lampRunPane = document.getElementById('lamp-run-pane');
  if (lampOpPane) setLamp(lampOpPane, j.op_live ? 'green' : 'gray');
  if (lampRunPane) setLamp(lampRunPane, j.run_live ? 'green' : 'gray');
  if (window.commandSender) {{
    window.commandSender.updateLamps({{ opLive: !!j.op_live, runLive: !!j.run_live }});
  }}
  if (j.sync) renderSync(j.sync);
  refreshOwnership(st);
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
  const parsed = (j.op_parsed || {{}});
  const completionChanged = !!parsed.completion_id &&
    parsed.completion_id !== (st.completionAtSend||'') &&
    parsed.completion_id !== (st.lastCompletion||'');
  if (reconcileLegacyTimeout(st,j)) {{
    renderTabs();
    applyState(st);
    return;
  }}
  if (st.waiting) {{
    setLamp(lampOp, 'yellow');
    setLamp(lampRun, j.run_live ? 'yellow' : 'red');
    setPollBusy(true);
    const now = Date.now();
    const age = st.waitStartedAt ? now-st.waitStartedAt : 0;
    const meaningfulKey = [parsed.body||'',parsed.completion_id||''].join('|');
    if (meaningfulKey && meaningfulKey !== st.lastMeaningfulKey) {{
      st.lastProgressAt = now;
      st.lastMeaningfulKey = meaningfulKey;
    }}
    if (!j.op_live) {{
      const reply='失败 · trigger '+opState;
      addBubble('fail',reply,parsed);
      logLine('err','本轮失败 · trigger pane 已离线');
      st.finalOp='red'; st.finalRun=j.run_live?'green':'red';
      st.waiting=false; st.pending=null; st.pollQuiet=0; st.waitStartedAt=0; st.lastPollKey='';
      setLamp(lampOp,st.finalOp); setLamp(lampRun,st.finalRun); setPollBusy(false);
      renderTabs();
      await persistTabsNow();
    }} else if (parsed.phase === 'idle' && completionChanged) {{
      const reply=parsed.body || paneDelta(st.opAtSend,j.op_text) || '本轮已完成';
      addBubble('ans',reply,parsed);
      st.lastCompletion=parsed.completion_id;
      st.finalOp='green'; st.finalRun=j.run_live?'green':'red';
      logLine('done','本轮结束 · '+(parsed.model||'')+(parsed.elapsed?' · '+parsed.elapsed:''));
      st.waiting=false; st.pending=null; st.pollQuiet=0; st.waitStartedAt=0;
      st.lastPollKey=''; st.completionAtSend='';
      setLamp(lampOp,st.finalOp); setLamp(lampRun,st.finalRun); setPollBusy(false);
      renderTabs();
      await persistTabsNow();
    }} else if (j.op_auto === false && parsed.phase !== 'running') {{
      const reply='trigger 当前不是 auto 模式；消息已发出，但可能在等待授权。前端已停止自动轮询，可点击上方“trigger 转为 auto”恢复原会话后继续。';
      addBubble('fail',reply,parsed);
      logLine('err','停止轮询 · trigger 非 auto 模式');
      st.finalOp='red'; st.finalRun=j.run_live?'green':'red';
      st.waiting=false; st.pending=null; st.pollQuiet=0; st.waitStartedAt=0; st.lastPollKey='';
      setLamp(lampOp,st.finalOp); setLamp(lampRun,st.finalRun); setPollBusy(false);
      renderTabs();
      await persistTabsNow();
    }} else if (parsed.phase === 'running') {{
      st.pollQuiet=0;
      if (st.pending) st.pending.status='running';
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
        if (st.pending) st.pending.status='attention';
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
      if (st.pollQuiet >= 8 && parsed.phase === 'unknown') {{
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
        st.pending = null;
        st.pollQuiet = 0;
        st.waitStartedAt = 0;
        st.lastPollKey = '';
        renderTabs();
        await persistTabsNow();
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
async function handleSend(targetSide, prompt) {{
  const st = activeTab;
  if (!st || !st.name || !prompt || st.waiting) return;
  let baseline = {{}};
  try {{
    const baselineResponse = await fetch('/api/tunnel?t=' + encodeURIComponent(st.name));
    if (baselineResponse.ok) baseline = await baselineResponse.json();
  }} catch (_) {{}}
  const baselineParsed = baseline.op_parsed || {{}};
  st.lastAsk = prompt;
  const preview = st.lastAsk.replace(/\\s+/g, ' ').slice(0, 80);
  addBubble('ask', st.lastAsk);
  logLine('send', preview || '(empty)');
  st.opAtSend = baseline.op_text || st.lastOp || '';
  st.lastCompletion = baselineParsed.completion_id || st.lastCompletion || '';
  st.completionAtSend = baselineParsed.completion_id || st.lastCompletion || '';
  st.waiting = true;
  st.pollQuiet = 0;
  st.waitStartedAt = Date.now();
  st.lastProgressAt = st.waitStartedAt;
  st.lastMeaningfulKey = '';
  st.longWarned = st.stallWarned = st.attentionWarned = false;
  st.pending = {{
    id: 'turn-' + st.waitStartedAt.toString(36) + '-' + Math.random().toString(36).slice(2, 10),
    status: 'pending',
    startedAt: new Date(st.waitStartedAt).toISOString(),
    baselineCompletion: st.completionAtSend,
  }};
  setLamp(lampOp, 'yellow');
  setLamp(lampRun, 'yellow');
  setPollBusy(true);
  renderTabs();
  try {{
    await persistTabsNow();
  }} catch(err) {{
    const msg = '未发送：pending turn 无法持久化 · ' + String(err.message || err);
    logLine('err', msg); addBubble('fail', msg);
    st.waiting = false; st.pending = null; st.waitStartedAt = 0; st.finalOp = 'red';
    setLamp(lampOp, 'red'); setPollBusy(false); renderTabs();
    throw err;
  }}
  const body = new URLSearchParams({{ t: st.name, side: targetSide, text: prompt }});
  const r = await fetch('/send', {{ method: 'POST', headers: {{ 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' }}, body }});
  if (!r.ok) {{
    const err = await r.text();
    logLine('err', err);
    addBubble('fail', err);
    st.finalOp = 'red';
    st.waiting = false;
    st.pending = null;
    st.waitStartedAt = 0;
    setLamp(lampOp, 'red');
    setLamp(lampRun, st.finalRun);
    setPollBusy(false);
    renderTabs();
    await persistTabsNow();
    throw new Error(err);
  }}
  st.lastSent = Date.now();
  st.waiting = true;
  st.pollQuiet = 0;
  logLine('send', '已提交到 ' + (targetSide === 'run' ? 'bullet' : 'trigger') + '，开始轮询');
  renderTabs();
  await persistTabsNow();
  tick();
}}

async function handleInterrupt(targetSide, kind) {{
  const st = activeTab;
  if (!st || !st.name) {{
    throw new Error('请先选择隧道');
  }}
  const body = new URLSearchParams({{
    t: st.name,
    side: targetSide === 'run' ? 'run' : 'op',
    kind: kind || 'ctrl_c',
  }});
  const r = await fetch('/api/interrupt', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' }},
    body
  }});
  if (!r.ok) {{
    const text = await r.text();
    let msg = text;
    try {{
      const p = JSON.parse(text);
      msg = (p.error && p.error.message) || text;
    }} catch(_) {{}}
    throw new Error(msg);
  }}
  // 中断成功：解除前端等待阻塞状态
  st.waiting = false;
  st.pending = null;
  st.waitStartedAt = 0;
  st.pollQuiet = 0;
  st.lastPollKey = '';
  setPollBusy(false);
  setLamp(lampOp, st.finalOp || 'gray');
  setLamp(lampRun, st.finalRun || 'gray');
  renderTabs();
  await persistTabsNow();
  const kindLabel = kind === 'escape' ? 'Escape 中断' : 'Ctrl+C 强行打断';
  const targetLabel = targetSide === 'run' ? 'Bullet (run_*)' : 'Trigger (op_*)';
  logLine('done', '已向 ' + targetLabel + ' 发送 ' + kindLabel + '，解除等待锁定');
  addBubble('ans', '🛑 [系统] 已向 ' + targetLabel + ' 发送 ' + kindLabel + '。前端轮询锁定已重置。');
  tick();
}}

sendf.addEventListener('submit', async (e) => {{
  e.preventDefault();
  const targetSide = (document.querySelector('input[name="send-target"]:checked')?.value) || 'op';
  try {{
    await handleSend(targetSide, box.value.trim());
    box.value = '';
  }} catch(_) {{}}
}});
async function postForm(url, fields) {{
  const body = new URLSearchParams(fields);
  const r = await fetch(url, {{ method: 'POST', headers: {{ 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' }}, body }});
  const text = await r.text();
  if (!r.ok) {{
    try {{
      const payload=JSON.parse(text), err=payload.error||{{}}, detail=err.detail||{{}};
      throw new Error([err.code,detail.reason,err.message].filter(Boolean).join(' · ')||text);
    }} catch(parsed) {{ if(parsed instanceof SyntaxError) throw new Error(text); throw parsed; }}
  }}
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
document.getElementById('btn-plan').addEventListener('click',()=>refreshOwnership(activeTab));
document.getElementById('btn-handoff').addEventListener('click',()=>executeResume(false));
async function executeResume(force) {{
  const st=activeTab; if(!st||!st.name) return;
  if(force) {{
    const typed=prompt('高风险操作：输入隧道全名确认 Force Resume。安全门（未知探测、重复 writer、native conflict、旧证据）仍不可绕过：','');
    if(typed!==st.name) {{ logLine('err','Force Resume 已取消：确认名称不匹配'); return; }}
  }}
  try {{
    const j=await postForm('/api/resume',{{t:st.name,force:force?'1':'0',confirm:force?st.name:''}});
    logLine('done',(force?'Force Resume':'Resume')+' 完成 · generation '+ownValue((j.data||{{}}).ownership_generation));
    await refreshRows(); await tick(); await refreshOwnership(st);
  }} catch(err) {{ logLine('err',(force?'Force Resume':'Resume')+' 失败 · '+String(err.message||err)); await refreshOwnership(st); }}
}}
document.getElementById('btn-resume').addEventListener('click',()=>executeResume(false));
document.getElementById('btn-force-resume').addEventListener('click',()=>executeResume(true));
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
document.querySelectorAll('input[name="send-target"]').forEach(radio => {{
  radio.addEventListener('change', e => {{
    const isBullet = e.target.value === 'run';
    const hint = document.getElementById('send-target-hint');
    if (hint) hint.textContent = isBullet ? '将向 Bullet pane (run_*) 注入 send-keys' : '将向 Trigger pane (op_*) 注入 send-keys';
  }});
}});
loadConfig();
restoreTabs({json.dumps(selected)});

</script>
    """
    return _shell(_nav("tunnels"), body, "dt web · 隧道")
