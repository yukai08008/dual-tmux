# v0.4.48 PRD — 飞书扫码 Web 与 tom7r 事件桥

> 父版本：v0.4.47（PR #11）
> 起草日期：2026-08-31
> 类型：Web 版（偶数，正式发布）
> 范围来源：正式列装计划

## 0. 一句话目标

让用户在 dt Web 中完成飞书配置、扫码绑定、状态查看和解绑，并通过 tom7r 可靠邮箱桥把飞书 OAuth callback/命令送到 NAT 后的 Client 执行。

## 1. 范围与不变量

### 1.1 In-scope

- Web 飞书页面：非秘密配置、QR、绑定状态、解绑、桥同步诊断。
- 本地 callback（开发/直达场景）和 tom7r callback 邮箱路由。
- tom7r bridge HTTP：health、OAuth callback、飞书 URL verification 与消息事件接收。
- operator identity hash → Client 路由注册；Client inbox/outbox 可靠交换。
- `dt tick` 消费 callback/command，结果写 outbox；已处理 message ID 本地防重放。
- 飞书文本结果与确认信息的桥接响应数据合同。

### 1.2 Out-of-scope

- 未获得企业 App 凭据前不声称真实生产飞书 E2E 已完成。
- bridge 不获得 SSH/任意 shell/upgrade/hotfix/cron 权限。
- 不自动开放本地 Web 到公网；Web 继续只监听 `127.0.0.1`。

### 1.3 不变量

- App Secret/OAuth token 不进入 QR、Hub 邮箱、tunnel JSON、Git 或审计日志。
- Hub 仅保存 state/identity 摘要、事件信封和结果；实际控制只在已绑定 Client 经 ControlService 执行。
- 邮箱采用 write-then-rename；重复拉取由 event/state 单次消费保证幂等。
- local-only 核心能力不依赖 bridge；Hub 切换不删除飞书本地绑定。
- Web 写请求保持 same-origin；callback 仅允许带一次性 state 的 OAuth GET。
- 新页面必须通过应用内 Browser E2E；运行时数据不在 Git 追踪。

## 2. 顶层蓝图

```text
Feishu phone/cloud
       │ HTTPS callback/event
       ▼
tom7r bridge ── route registry (hash only)
       │ inbox/<client>       ▲ outbox/<client>
       ▼                      │
Client dt tick / Web sync ────┘
       │ PairingService / FeishuDispatcher
       ▼
ControlService → tmux/tunnel
```

## 3. Web 交互

导航新增“飞书”。配置表单不接受 secret 本体，只接受 secret 文件路径并展示来源。点击生成二维码后展示过期时间和授权链接；页面轮询 status/bridge sync。已绑定 operator 可单个或全部解绑。

## 4. 中心事件桥

bridge 使用独立 spool root，可部署在 tom7r。OAuth state 注册时只上传摘要与 Client；callback 按 state 摘要投递。绑定成功后上传 operator ID 摘要路由。消息事件按 sender ID 摘要投递。所有信封设大小上限、随机文件名和严格 Client 名校验。

## 5. 可靠性与切换影响

Client 不在线时 inbox 保留；再次 `dt tick` 或 Web 手动同步后消费。重复文件/事件不会重复执行。切到 local-only 后本地绑定仍在，但远程管理显示 bridge unavailable；重新指定同一或新 Hub 时重新注册路由，不改写 tunnel/session 数据。

## 6. 风险登记表

| ID | 严重度 | 风险 | 缓解 | 责任人 |
|---|---|---|---|---|
| R1 | high | 伪造飞书事件 | verification token；生产建议 Caddy TLS + 飞书 IP/签名策略 | PM |
| R2 | high | 邮箱重复消费破坏命令 | event_id 防重放 + 原子信封 + outbox 幂等 ID | Coder |
| R3 | high | Client 离线造成丢消息 | tom7r 持久 inbox，Client 拉取确认后清理 | Coder |
| R4 | medium | Hub 更换后旧路由残留 | 新 Hub 重注册；文档提供旧 Hub route prune | PM |
| R5 | medium | 未提供企业凭据无法验真实扫码 | 自动测试 + 浏览器 E2E；正式推广前补真实飞书 E2E | Tester |

## 7. 签名

Agent-PM-0.4.48
