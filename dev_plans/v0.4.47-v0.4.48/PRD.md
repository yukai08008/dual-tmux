# v0.4.48 PRD — 飞书扫码即用与常驻长连接

> 父版本：v0.4.47（PR #11）
> 起草日期：2026-08-31
> 类型：Web 版（偶数，正式发布）
> 范围来源：正式列装计划

## 0. 一句话目标

让用户无需提供 App ID、App Secret 或公网 callback，仅在 dt Web 扫码确认，即可自动创建飞书 PersonalAgent、启动受监督的 WebSocket 长连接并管理 tunnel。

## 1. 范围与不变量

### 1.1 In-scope

- 飞书官方 Device Registration（RFC 8628）：生成一次性 QR，扫码后自动获得 PersonalAgent 的 `client_id/client_secret`。
- 凭据由系统自动生成本机 0600 主密钥并使用 AEAD 加密保存，Web、日志、Hub 同步树均不暴露明文。
- Web 飞书页面只提供“扫码绑定、连接状态、解绑、重新连接”，不要求用户填写 App 或 callback 参数。
- `dt daemon` 常驻服务与 Feishu Connector Manager；启动时恢复已绑定应用，动态启动/停止 WS，心跳、退避重连和诊断。
- local-only 在 Client 运行 WS；Hub 模式允许 tom7r 持有连接租约并通过既有 inbox/outbox 路由到 Client。
- 同一应用单活租约 + `event_id` 防重放，模式切换先停旧连接再启新连接。
- 飞书文本结果与二次确认信息的回包合同。

### 1.2 Out-of-scope

- 不开放任意 shell、upgrade、hotfix、cron 或 SSH 配置权限。
- 不自动开放本地 Web 到公网；Web 继续只监听 `127.0.0.1`。
- 不支持手填 App 凭据作为默认用户流程；仅保留受控迁移入口用于历史安装。

### 1.3 不变量

- App Secret/OAuth token 不进入 QR、Web 响应、Hub 邮箱、tunnel JSON、Git 或审计日志。
- 凭据只以 AEAD 密文落盘；主密钥必须为当前用户所有、非符号链接且 mode 0600。
- Hub 只保存加密安装、租约、identity 摘要、事件信封和结果；实际控制只在已绑定 Client 经 ControlService 执行。
- 邮箱采用 write-then-rename；重复拉取由 event/state 单次消费保证幂等。
- local-only 核心能力不依赖 bridge；Hub 切换不删除飞书本地绑定。
- Web 写请求保持 same-origin；Device Code、轮询结果和凭据永不进入浏览器。
- `dt web` 不是 WS 生命周期所有者；关闭 Web 不得让已绑定 Bot 下线。
- 新页面必须通过应用内 Browser E2E；运行时数据不在 Git 追踪。

## 2. 顶层蓝图

```text
Feishu scan ── Device Registration ── encrypted installation
                                            │ single-owner lease
                         ┌──────────────────┴──────────────────┐
                         ▼                                     ▼
                 Client dt daemon                       tom7r dt daemon
                    WS long conn                 WS long conn + mailbox
                         │                                     │
                         └────────── ControlService ───────────┘
                                        │
                                   tmux/tunnel
```

## 3. Web 交互

导航新增“飞书”。未绑定时只有“扫码绑定”；点击后展示官方一次性二维码和过期时间，页面轮询安装状态。成功后显示 Bot、扫码操作者、WS 所有者、连接状态、最后消息/错误与解绑按钮。

## 4. Device Registration 与凭据

`POST https://accounts.feishu.cn/oauth/v1/app/registration` 的 begin/poll 协议只在服务端执行。Device Code 使用 10 分钟 TTL；成功响应中的应用凭据立即加密，明文仅存在于当前调用栈。安装记录与租约原子写入。

## 5. 常驻服务与 WS

`dt daemon` 是独立于 Web 的常驻进程。它加载 active installation，取得本地或 Hub 租约后启动官方 `lark-oapi` WS Client。崩溃和网络错误按 5/15/30/60/120 秒退避；解绑、凭据轮换或租约丢失会终止旧 connector。状态写入本地 0600 runtime 文件供 CLI/Web/Doctor 只读展示。

## 5. 可靠性与切换影响

Client 不在线时 Hub inbox 保留；再次上线后消费。重复文件/事件不会重复执行。切到 local-only 时先释放 Hub 租约，再由本地 daemon 接管；连接切换不改写 tunnel/session 数据。租约异常时宁可 Bot 暂时离线，也不允许双活执行。

## 6. 风险登记表

| ID | 严重度 | 风险 | 缓解 | 责任人 |
|---|---|---|---|---|
| R1 | high | 应用凭据泄露 | 自动主密钥、AEAD、0600、响应/日志/同步边界测试 | Coder |
| R2 | high | 邮箱重复消费破坏命令 | event_id 防重放 + 原子信封 + outbox 幂等 ID | Coder |
| R3 | high | Client 离线造成丢消息 | tom7r 持久 inbox，Client 拉取确认后清理 | Coder |
| R4 | medium | Hub 更换后旧路由残留 | 新 Hub 重注册；文档提供旧 Hub route prune | PM |
| R5 | medium | 企业策略禁止 PersonalAgent 自动创建 | 自动协议测试 + Browser E2E；正式推广前用真实企业账号扫码验证 | Tester |
| R6 | high | Web 退出导致 Bot 离线 | 独立 daemon + 服务管理器，不由 Web 持有 WS | Coder |
| R7 | high | local/Hub 同时消费 | 单活租约、fencing token、event_id 去重 | Coder |

## 7. 签名

Agent-PM-0.4.48
