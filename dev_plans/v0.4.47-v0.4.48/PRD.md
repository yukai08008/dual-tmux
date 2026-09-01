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

- 一个 dual-tmux deployment 只有一个总 PersonalAgent；多台 Client 和多个 Web 页面共享它。再次扫码只能走显式“更换机器人”事务，不能创建或覆盖第二套 active installation。
- App Secret/OAuth token 不进入 QR、Web 响应、Hub 邮箱、tunnel JSON、Git 或审计日志。
- 凭据只以 AEAD 密文落盘；主密钥必须为当前用户所有、非符号链接且 mode 0600。
- Hub 只保存加密安装、租约、identity 摘要、事件信封和结果；实际控制只在已绑定 Client 经 ControlService 执行。
- 邮箱采用 write-then-rename；重复拉取由 event/state 单次消费保证幂等。
- local-only 核心能力不依赖 bridge；Hub 切换不删除飞书本地绑定。
- Web 写请求保持 same-origin；Device Code、轮询结果和凭据永不进入浏览器。
- `dt web` 不是 WS 生命周期所有者；关闭 Web 不得让已绑定 Bot 下线。
- 任一拓扑最多一个 active WS owner；owner 必须持有原子 lease 与 generation，旧 generation 恢复后保持 standby。
- Hub deployment ID 为配置中的 `user`；同一 `server + user` 的多 Client 共享一个 PersonalAgent，不同 `user` 的 credentials、routes、mailbox、lease 和 daemon 必须完全隔离。
- Hub 同步完成后，所有 daemon 需要读取/写入的飞书目录和信封必须归一化为 Hub 服务身份：目录 0700、文件 0600；不得保留 Client UID/GID 导致服务不可读。
- 一个 Hub daemon 只能挂载一个 deployment 根目录，不得通过挂载用户父目录获得跨租户读取能力。
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

连接拓扑与 tunnel 数据模式是两个维度：local-only 默认使用本地独立 WS；Hub 模式默认由 tom7r 常驻 WS；双 Client 接管是显式高级拓扑，候选 Client 通过 tom7r 的原子 lease/generation 选出唯一 active，其余保持 standby。仅启动 `dt web` 永远不参与 WS 竞选。

## 5. 可靠性与切换影响

Client 不在线时 Hub inbox 保留；再次上线后消费。重复文件/事件不会重复执行。切到 local-only 时先释放 Hub 租约，再由本地 daemon 接管；连接切换不改写 tunnel/session 数据。租约异常时宁可 Bot 暂时离线，也不允许双活执行。

## 6. Hub 用户名租户与 daemon 供给

中心服务器继续使用既有目录，不引入新的租户数据库：

```text
~/<user>/dual-tmux/
├── tunnels/ entries/ activity/ locks/
└── feishu/
    ├── credential.key + installation.json
    ├── bridge/{routes,commands,responses,callbacks,pairing}/
    └── daemon-status.json
```

隔离键为 `server + user`。同一用户的笔记本、台式机等 Client 属于同一 deployment；不同用户即使使用同一 tom7r、相同飞书企业或相同命令，也只访问各自目录。服务端为每个已安装飞书机器人的用户名幂等供给一个 daemon 实例，实例只挂载 `~/<user>/dual-tmux` 到 `/data`，容器名/服务实例名由经过合法性校验的 user 派生。解绑只停止该用户名的实例，不影响其他用户。

本版先完成：单租户 ownership 修复、按用户名显式幂等供给、双用户名隔离验证和真实 `/dt ls` 闭环。未来若改为中心控制器自动发现/供给，仍必须保持相同目录与进程边界，不能把多个租户凭据加载进同一个 WS 进程。

### 6.1 Hub 存储准备事务

发布 installation 或 route 前后都执行同一幂等准备流程：创建固定白名单目录；将目录归一化为 Hub 服务 UID/GID 和 0700；将 credentials、route 与 mailbox 信封归一化为同一身份和 0600；最后用实际 daemon 身份执行 credentials 可解密、routes 可读、commands/responses 可原子创建的探针。任一步失败时不宣告安装成功，并返回不包含真实路径和身份数据的结构化错误码。

### 6.2 兼容与无害切换

- 修复不改变 JSON 格式、route hash、event ID 或 Client 名称，现有机器人无需重新扫码。
- ownership 修复只作用于当前 `~/<user>/dual-tmux/feishu` 白名单，不递归修改 tunnels、sessions 或其他用户目录。
- 升级时先修复存储，再重启当前租户 daemon；WS 短暂重连期间消息由飞书/邮箱重试，event ID 防止重复执行。
- 同名 user 被视为同一 deployment，这是显式共享而非数据串租；公司账号侧必须保证用户名唯一且不可由普通用户冒用。

## 7. 风险登记表

| ID | 严重度 | 风险 | 缓解 | 责任人 |
|---|---|---|---|---|
| R1 | high | 应用凭据泄露 | 自动主密钥、AEAD、0600、响应/日志/同步边界测试 | Coder |
| R2 | high | 邮箱重复消费破坏命令 | event_id 防重放 + 原子信封 + outbox 幂等 ID | Coder |
| R3 | high | Client 离线造成丢消息 | tom7r 持久 inbox，Client 拉取确认后清理 | Coder |
| R4 | medium | Hub 更换后旧路由残留 | 新 Hub 重注册；文档提供旧 Hub route prune | PM |
| R5 | medium | 企业策略禁止 PersonalAgent 自动创建 | 自动协议测试 + Browser E2E；正式推广前用真实企业账号扫码验证 | Tester |
| R6 | high | Web 退出导致 Bot 离线 | 独立 daemon + 服务管理器，不由 Web 持有 WS | Coder |
| R7 | high | local/Hub 同时消费 | 单活租约、fencing token、event_id 去重 | Coder |
| R8 | high | rsync 保留 Client UID 使 Hub daemon 无法读写 mailbox | Hub 服务身份归一化 + daemon 身份读写探针 + cap-drop 容器回归 | Coder |
| R9 | high | 多用户共用中心服务器时跨租户读取或错误共用机器人 | `server + user` namespace、每用户独立 daemon/挂载、双用户隔离 E2E | Coder/Tester |
| R10 | medium | 用户名重复导致非预期共享 deployment | 初始化/供给时合法性与唯一性检查，企业账号统一分配 | PM/Ops |

## 8. 签名

Agent-PM-0.4.48
