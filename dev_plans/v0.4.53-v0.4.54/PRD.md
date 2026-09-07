# v0.4.54 PRD — Ownership 与安全接管 Web

> 父版本：`v0.4.53-final`（实现基线包含 `v0.4.53.post1`）  
> 起草日期：2026-09-07  
> 类型：Web 版（偶数，完整封板后发布）  
> 范围来源：v0.4.53 `API_FREEZE.md`、BL-RUNTIME-001、失效 v0.4.50 草案重新基线

## 0. 一句话目标

让用户在 Web 准确看见 Lease、两侧运行/连接/进展/writer/native snapshot，并以缓存预检、显式 handoff 和 generation fencing 安全接管三种 Agent 会话。

## 1. 范围与不变量

### 1.1 In-scope

- 独立展示 Lease holder、instance、generation、TTL/age 与 evidence freshness。
- trigger/bullet 分别展示 runtime、attached、semantic progress、writer status/count/PIDs 和 native snapshot。
- 展示与 `dt resume --plan` 同形的 `safe/action/reason/steps` 预检。
- handoff 请求、pending/acked/rejected 状态与精确拒绝原因。
- OpenCode、Codex、Claude 一致展示；local-only 明示“无 Hub lease”。
- force 输入隧道全名二次确认；未知探测、duplicate writer、native conflict、过期证据不可绕过。

### 1.2 Out-of-scope

- 不修改 Lease v2、native snapshot schema、session import 与 handoff 顺序。
- 不自动终止 Agent 或 duplicate writer。
- 不在本版重做 terminal 500 行、自适应轮询、交接摘要和 Agent 智能入口。

### 1.3 不变量

- Web GET 只读取本地 binding、health 和 daemon/tick 生成的 Ownership cache，不触发 Hub pull、SSH、writer 或 tmux 探测。
- 打开页面、刷新或切换 tab 不自动 resume/handoff/claim。
- 所有变更通过 ControlService；失败返回结构化、精确原因。
- native conflict、duplicate/unknown writer、stale cache 一律 fail closed。
- 运行时 cache、lease、handoff 与 session 数据不进入 Git。
- 前端测试覆盖新功能，升级不改变 config/tunnel/session binding。

### 1.4 历史关系

- v0.4.51 冻结 Ownership API；v0.4.53 增加 Codex/Claude native snapshot 状态。
- v0.4.50 草案因当时 API 不存在已归档；本版从 v0.4.53 冻结合约重新建立，不继承其版本血缘假设。

## 2. 数据流

```text
daemon / dt tick
  -> Lease v2 + semantic evidence + writer/native probes
  -> ~/.dual-tmux/ownership-cache/<tunnel>.json (atomic)
  -> Web GET /api/ownership, /api/resume/plan (cache only)

user explicit action
  -> Web POST handoff/resume
  -> ControlService
  -> frozen Ownership / generation fencing contract
```

## 3. Web 事实面板

Lease 与 trigger/bullet 分块展示原始事实，不用单一红绿灯覆盖未知状态。Cache 显示采集时间、age、fresh/stale；缺失或超过 180 秒时 plan 必须停止。local-only 的 Lease source 为 `local`，TTL 显示 `n/a`。

## 4. 安全接管

页面先展示缓存 plan。`request_handoff` 仅在 foreign + idle + detached + writer 明确正常 + snapshot 无冲突时启用；Resume 在 plan safe 时启用。真正提交时 ControlService 重新执行实时预检，缓存结果不是授权令牌。Force 只影响可安全 claim 的竞争窗口，不是绕过安全门的后门。

## 5. 不变量自验

- GET plan 时 monkeypatch live snapshot 为失败，接口仍从缓存返回。
- 页面源码不存在选中 tunnel 后调用 automatic resume 的路径。
- cache missing/stale、三客户端 duplicate writer、native conflict 均禁用操作。
- `git ls-files data/ | wc -l == 0`。

## 6. 风险登记表

| ID | 风险 | 缓解 | 严重度 | 责任人 |
|---|---|---|---|---|
| R1 | Web 高频刷新造成 SSH/进程探测风暴 | GET 只读原子 cache；后台采集 | high | Coder |
| R2 | 旧 cache 被当作安全授权 | 180 秒 freshness gate；提交时实时重验 | critical | Coder + Tester |
| R3 | Force 被误解为绕过冲突 | 精确提示、全名确认、底层 plan 仍 fail closed | critical | PM + Tester |
| R4 | 页面打开自动创建 writer | 移除 auto-resume；副作用测试 | critical | Coder |
| R5 | 三客户端状态展示漂移 | 消费冻结 schema + fixture/contract tests | high | Tester |

## 7. 签名

`Agent-PM-0.4.54`
