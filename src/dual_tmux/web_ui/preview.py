from __future__ import annotations

import html
from pathlib import Path
from . import get_theme_css, get_components_css, get_components_js

_UI_DIR = Path(__file__).resolve().parent

COMPONENTS_META = [
    {
        "id": "terminal",
        "name": "双端终端视窗 (DualTerminal)",
        "desc": "Trigger / Bullet 实时输出渲染，智能吸底防抢滚动条，分屏切换，一键复制",
    },
    {
        "id": "sender",
        "name": "指令发送器 (CommandSender)",
        "desc": "支持 Cmd/Ctrl+Enter 快捷发送，目标端切换，发送反馈与历史回溯",
    },
    {
        "id": "picker",
        "name": "隧道选择与 Tabs (TunnelPicker)",
        "desc": "多会话 Tab 栏，模糊搜索，DST / 草稿徽标与状态展示",
    },
    {
        "id": "occupancy",
        "name": "独热占有卡片 (OccupancyCard)",
        "desc": "持有者、世代纪元、归属仲裁与接管安全守卫",
    },
    {
        "id": "toast",
        "name": "悬浮通知系统 (ToastManager)",
        "desc": "轻量全局 Toast 提示（成功、错误、警告、信息），自动淡入淡出",
    },
    {
        "id": "thread",
        "name": "问答对话流 (TurnThread)",
        "desc": "优雅的对话气泡，包含提问、回答、耗时与模型标签",
    },
    {
        "id": "lifecycle",
        "name": "运维工具折叠卡片 (LifecycleToolbar)",
        "desc": "低频操作收纳，Freeze 固化、重连、Drop、模型切换",
    },
]


def render_component_preview(component_id: str = "terminal") -> str:
    theme_css = get_theme_css()
    comp_css = get_components_css()
    comp_js = get_components_js()
    preview_js_path = _UI_DIR / "preview.js"
    preview_js = preview_js_path.read_text(encoding="utf-8") if preview_js_path.exists() else ""

    matched = next((c for c in COMPONENTS_META if c["id"] == component_id), COMPONENTS_META[0])
    current_id = matched["id"]

    nav_links = []
    for item in COMPONENTS_META:
        active = "active" if item["id"] == current_id else ""
        nav_links.append(
            f'<a href="/components?c={item["id"]}" class="dt-sandbox-nav-item {active}">'
            f'  <div class="dt-nav-title">{html.escape(item["name"])}</div>'
            f'  <div class="dt-nav-desc">{html.escape(item["desc"])}</div>'
            f'</a>'
        )
    nav_html = "\n".join(nav_links)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>组件独立预览 · {html.escape(matched['name'])} - dual-tmux</title>
<style>
{theme_css}
{comp_css}

body {{
  margin: 0;
  padding: 0;
  background: var(--dt-bg-canvas);
  color: var(--dt-text-primary);
  font-family: var(--dt-font-sans);
  height: 100vh;
  display: flex;
  overflow: hidden;
}}

.dt-sandbox-sidebar {{
  width: 280px;
  background: var(--dt-bg-surface);
  border-right: 1px solid var(--dt-border-subtle);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}}

.dt-sandbox-sidebar-header {{
  padding: 16px;
  border-bottom: 1px solid var(--dt-border-subtle);
}}
.dt-sandbox-sidebar-header h2 {{
  margin: 0 0 4px 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--dt-text-primary);
}}
.dt-sandbox-sidebar-header p {{
  margin: 0;
  font-size: 11.5px;
  color: var(--dt-text-muted);
}}

.dt-sandbox-nav-list {{
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}}

.dt-sandbox-nav-item {{
  display: block;
  text-decoration: none;
  padding: 10px 12px;
  border-radius: var(--dt-radius-md);
  border: 1px solid transparent;
  transition: all 0.15s ease;
}}
.dt-sandbox-nav-item:hover {{
  background: var(--dt-bg-surface-raised);
}}
.dt-sandbox-nav-item.active {{
  background: var(--dt-primary-subtle);
  border-color: rgba(59, 130, 246, 0.4);
}}
.dt-nav-title {{
  font-size: 12.5px;
  font-weight: 600;
  color: var(--dt-text-primary);
}}
.dt-sandbox-nav-item.active .dt-nav-title {{
  color: #60a5fa;
}}
.dt-nav-desc {{
  font-size: 11px;
  color: var(--dt-text-muted);
  margin-top: 2px;
  line-height: 1.35;
}}

.dt-sandbox-main {{
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--dt-bg-canvas);
  overflow-y: auto;
}}

.dt-sandbox-header {{
  padding: 14px 24px;
  background: var(--dt-bg-surface);
  border-bottom: 1px solid var(--dt-border-subtle);
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.dt-sandbox-header h1 {{
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}}
.dt-sandbox-header a.back-link {{
  color: var(--dt-text-secondary);
  text-decoration: none;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}}
.dt-sandbox-header a.back-link:hover {{
  color: var(--dt-primary);
}}

.dt-sandbox-content {{
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1200px;
  width: 100%;
  box-sizing: border-box;
  margin: 0 auto;
}}

.dt-control-panel {{
  background: var(--dt-bg-surface);
  border: 1px solid var(--dt-border-subtle);
  border-radius: var(--dt-radius-lg);
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.dt-control-title {{
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #60a5fa;
  display: flex;
  align-items: center;
  gap: 6px;
}}
.dt-control-actions {{
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}}

.dt-preview-stage {{
  width: 100%;
  min-height: 200px;
}}
</style>
</head>
<body>
  <aside class="dt-sandbox-sidebar">
    <div class="dt-sandbox-sidebar-header">
      <h2>🧩 组件沙箱画廊</h2>
      <p>独立查看、交互与验收各个 Web 组件</p>
    </div>
    <div class="dt-sandbox-nav-list">
      {nav_html}
    </div>
  </aside>

  <main class="dt-sandbox-main">
    <header class="dt-sandbox-header">
      <div>
        <h1>{html.escape(matched['name'])}</h1>
        <div style="font-size:12px; color:var(--dt-text-muted); margin-top:2px;">{html.escape(matched['desc'])}</div>
      </div>
      <a href="/tunnels" class="back-link">返回主控制台 →</a>
    </header>

    <div class="dt-sandbox-content">
      <div class="dt-control-panel" id="dt-tester-controls"></div>
      <div class="dt-preview-stage" id="dt-component-stage"></div>
    </div>
  </main>

  <script>
  {comp_js}
  {preview_js}
  </script>
</body>
</html>
"""
