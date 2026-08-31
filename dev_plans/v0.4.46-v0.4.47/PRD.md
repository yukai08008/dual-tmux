# v0.4.47 PRD — 飞书绑定与鉴权 API

> 父版本：v0.4.46
> 起草日期：2026-08-31
> 类型：API 版（奇数，不单独发布）
> 范围来源：正式列装计划

## 0. 一句话目标

建立可由本地 CLI、未来 Web 与 tom7r 事件桥共同调用的飞书安全控制内核，让扫码身份、事件防重放、命令授权、二次确认和审计先于 UI 落地。

## 1. 范围与不变量

### 1.1 In-scope

- 飞书 App ID、回调地址、secret 文件位置与 operator allowlist 配置合同。
- App Secret 仅从环境变量或权限为 `0600` 的本地文件读取。
- 高熵、限时、一次性 OAuth pairing state；严格 callback 校验。
- `open_id`、`union_id`、`user_id` 身份绑定和 allowlist。
- `event_id` 防重放；飞书命令解析、授权、执行与审计。
- drop/remove 的短时、单次、绑定操作者和目标的二次确认 token。
- OAuth HTTP 交换使用可注入 transport，测试不需要真实凭据。

### 1.2 Out-of-scope

- v0.4.48：Web 二维码、绑定状态与解绑 UI、飞书消息卡片。
- v0.4.48：tom7r 中心事件桥、事件回调/长连接和真实企业飞书 E2E。
- 飞书侧 upgrade、hotfix、cron 安装、任意 shell、SSH key/config 修改永久禁止。

### 1.3 不变量

- 飞书 Secret、OAuth token、身份凭据不进入 Git、tunnel JSON 或 Hub 同步树。
- 飞书只调用既有 `ControlService`，不形成第二套业务执行逻辑。
- 未绑定身份、重复事件、过期/复用 state 和确认 token 均 fail closed。
- 运行时数据不在 Git 追踪中；现有 local/Hub 数据和三客户端生命周期不变。
- v0.4.48 前端 E2E 必须覆盖扫码和管理路径。

### 1.4 与历史版本的关系

v0.4.47 复用 v0.4.40 的 ControlService、v0.4.42 的 health/recovery 和 v0.4.46 的全功能控制面，仅新增飞书安全适配层；奇数版完成后直接进入 v0.4.48。

## 2. 顶层蓝图

```text
Feishu OAuth / Event
        │
        ▼
pairing state ─ identity allowlist ─ event replay guard
        │                         │
        └──────────┬──────────────┘
                   ▼
             command policy
                   │ destructive: one-time confirmation
                   ▼
             ControlService
                   │
             audit events.jsonl
```

## 3. 配置与秘密边界

公开配置和 operator binding 存于本机 `DUAL_TMUX_HOME/feishu/`，文件原子写入且权限 `0600`。Secret 通过 `DT_FEISHU_APP_SECRET` 或显式 secret 文件解析；权限宽于 owner read/write 时拒绝启动。

## 4. Pairing 与身份

`pair` 生成至少 256-bit 随机 state，仅保存摘要和过期时间。callback 先原子消费 state，再交换 code；失败 state 也不可重放。OAuth 返回的任一稳定身份加入本地 binding。预配置 allowlist 可限制允许完成绑定的企业身份。

## 5. 命令与确认

支持 `/dt ls|show|send|health|freeze|resume|recover|drop|rm`。解析器不执行 shell 展开。drop/rm 首次请求返回确认 token；token 绑定 operator、动作和 tunnel，限时且单次消费。维护命令与未知命令默认拒绝。

## 6. 风险登记表

| ID | 严重度 | 风险 | 缓解措施 | 责任人 |
|---|---|---|---|---|
| R1 | high | secret 或 token 被同步/提交 | 独立本地目录、0600、Git/Hub 边界测试 | Coder |
| R2 | high | 回调/事件重放导致重复破坏 | state/event/confirm 三层一次性存储 | Coder |
| R3 | high | 手机无法直达本机 127.0.0.1 | v0.4.48 由 tom7r 事件桥转发到已登记 Client | PM |
| R4 | medium | 多身份字段变化导致误拒绝 | 支持三种 ID，任一已绑定稳定 ID 即授权 | Coder |
| R5 | medium | 远程表面扩大维护权限 | 固定命令 allowlist，维护命令无映射 | Reviewer |

## 7. 签名

Agent-PM-0.4.47
