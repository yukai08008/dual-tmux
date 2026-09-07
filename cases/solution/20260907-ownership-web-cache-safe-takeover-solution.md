# Ownership Web cache 与安全接管方案

## 背景

v0.4.53 已冻结 Lease、writer、semantic progress、handoff 与 Codex/Claude native snapshot 合同，但 Web 仍会在选中离线 DST 时自动 Resume，也缺少可解释的接管面板。

## 根因

- Web 页面生命周期与 session mutation 耦合，刷新可能启动 writer。
- 实时 Ownership snapshot 包含 SSH、tmux 与进程探测，不适合由浏览器高频 GET 直接触发。
- 旧 UI 只给 Resume 按钮，未把 lease/runtime/attached/progress/writer/native snapshot 和拒绝原因展示给用户。

## 解决步骤

1. daemon/tick 在后台采集事实，原子写入 `~/.dual-tmux/ownership-cache/`。
2. Web 的 ownership/plan GET 只读本地 binding 与 cache，cache 超过 180 秒即 fail closed。
3. 移除页面选中、刷新和 tab 切换中的 auto-resume。
4. 按 Lease、trigger、bullet、接管结论四块展示冻结事实。
5. handoff 与 resume 改为显式 POST；提交时 ControlService 重新实时预检。
6. Force 要求输入隧道全名，只在安全的 claim 场景启用，不能绕过 unknown/duplicate/conflict/stale 门禁。

## 关键点

- Cache 是展示证据，不是接管授权。
- local-only 是正式模式，明确显示无 Hub lease。
- 后台 Ownership worker 与飞书 Connector 主循环分离，慢 SSH 探测不阻塞 WS supervision。
- 原有 Lease v2/native schema 未变化，v0.4.54 只消费 v0.4.53 freeze。

## 验证

- 299 tests 通过。
- Browser E2E 显示 Codex/Claude 双侧事实，reload 无 tmux mutation，console 无错误。
- Ruff、compileall、build、隔离安装和 Git runtime-data gate 通过。
