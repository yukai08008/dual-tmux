# dual-tmux CLI 与 Web 的定位、边界和共享内核

## 核心结论

dual-tmux 应坚持 **CLI-first**：CLI 是产品主入口、自动化接口、完整管理入口和最终逃生通道；Web 是建立在相同业务能力之上的多 Agent 可视化工作台。

在代码层面，Web 应复用“CLI 的操作内核”，而不是把 `dt` 可执行文件及其 stdout/stderr 当作内部 RPC 协议。

```text
CLI ─────┐
Web ─────┼──→ Application Operations / ControlService
Feishu ──┘                    │
                             ▼
                tmux / Hub / recovery / store
```

因此可以同时成立：

- **产品定位上以 CLI 为核心。**
- **业务语义由 CLI 首先定义。**
- **实现上将成熟的 CLI 逻辑下沉为可调用的共享操作内核。**
- **Web 不重新实现业务，也不依赖对 CLI 文本输出的解析。**

## CLI 的侧重点

CLI 适合离散、明确、可组合和可自动化的操作。

典型场景：

- 初始化和配置环境
- 创建、冻结、恢复、删除 tunnel
- SSH、Hub、cron、daemon、升级等宿主机维护
- 脚本和批量自动化
- 故障排查和底层状态检查
- 紧急恢复、强制抢占和精确控制
- 远程 SSH 登录后的无图形操作

例如：

```sh
dt new myapp
dt freeze myapp
dt resume myapp
dt health myapp --json
dt recover myapp --now
dt push
dt upgrade
```

CLI 的特点：

- 一次命令对应一次明确意图。
- 输入和输出适合脚本消费。
- 可以完整暴露高级参数和诊断信息。
- 不依赖浏览器状态。
- 适合低频但高权限、高风险的操作。
- Web 不可用时仍可独立管理整个系统。

因此，CLI 是 dual-tmux 的**工程控制面和最终逃生通道**。

## Web 的侧重点

Web 适合连续观察、多对象切换、状态聚合和交互式协作。

dual-tmux 的 Web 价值不是简单地把 CLI 命令做成按钮，而是让用户持续掌握多个 Agent 工作现场：

- 哪些 tunnel 正在运行
- Trigger 和 Bullet 分别在做什么
- 哪个 Agent 正在等待输入
- 哪个 tunnel 失联或需要恢复
- 最近一次输出发生了什么变化
- 当前 session、model、runtime 和 Hub owner 是谁
- 用户下一步应该介入哪个 tunnel
- 如何快速向指定 pane 发送下一条指令

Web 的主要工作区应当是：

```text
Tunnel 列表
    +
Trigger/Bullet 实时输出
    +
消息输入
    +
运行状态、待办和异常提示
```

而不是只提供：

```text
dt new / dt freeze / dt resume 的按钮集合
```

按钮是辅助能力；Web 的本质是**多 Agent 工作台**。

## CLI 与 Web 的差异

| 维度 | CLI | Web |
|---|---|---|
| 主要目标 | 精确执行和自动化 | 持续观察与交互 |
| 操作模型 | 一次命令、一次结果 | 长时间打开、状态持续变化 |
| 主要对象 | 单个 tunnel 或系统配置 | 多个 tunnel 和 pane |
| 状态来源 | 每次重新读取真实状态 | 后端真实状态 + 前端临时 UI 状态 |
| 自动化能力 | 强 | 弱 |
| 信息表达 | 原始、完整、可管道化 | 聚合、可视化、突出异常 |
| 高风险操作 | 完整支持 | 限制开放并要求明确确认 |
| 长耗时任务 | 终端等待或流式日志 | operation ID、阶段和进度事件 |
| 宿主机维护 | 适合 | 通常不开放 |
| 使用频率 | 按需调用 | 日常持续使用 |

可以用三个问题概括各层定位：

- CLI 回答：**准确执行哪一个动作？**
- Web 回答：**所有工作现在进行得怎么样，下一步应该介入哪里？**
- 共享操作内核回答：**这个动作在系统里的唯一业务语义是什么？**

## 两者应共享什么

CLI、Web 和 Feishu 应共享同一套业务内核：

```text
CLI ─┐
     ├──→ ControlService ──→ tmux / Hub / recovery / store
Web ─┘
```

应共享的内容包括：

- `ControlService` 或后续的 Application Operations
- 操作名称、参数含义和安全规则
- Agent capability registry
- tunnel/session DTO
- Hub 所有权和 generation fencing
- Trigger 独热接管：新端 ≤10 秒取得控制，旧端 detach/kill 后返回原 shell
- freeze/resume/recovery 逻辑
- 审计事件
- 稳定错误码
- 写操作确认规则

例如，CLI 和 Web 应调用同一个操作：

```python
# CLI adapter
result = operations.resume(name, force=False)

# Web adapter
result = operations.resume(name, force=False)
```

不能形成两套实现：

```text
CLI → ControlService
Web → 重新实现一套 resume
```

否则容易出现：

- CLI 能恢复但 Web 不能恢复
- 两边对 Hub 锁的理解不同
- Web 绕过 session fencing
- 删除确认和审计规则不一致
- 同一种错误返回不同结果

## 两者不需要共享什么

业务语义一致，不代表表现形式一致。

- CLI 可以输出 Rich 表格、简洁日志或 JSON。
- Web 可以使用卡片、状态灯、时间线和阶段进度。
- CLI 可以同步等待命令结束。
- Web 更适合把长耗时操作表示为异步 operation。
- CLI 参数结构不应机械地映射为 HTTP API。
- Web 的标签、布局、搜索和滚动位置不属于 CLI 业务状态。

同一个 resume 操作可以表现为：

```text
CLI:
  [ok] claimed dt-msg
  [ok] connected remote runtime
  [ok] resumed DST dt-msg

Web:
  申请 Hub 锁
      ↓
  重建 run_* pane
      ↓
  连接 SSH / Docker
      ↓
  检查并导入 session
      ↓
  恢复 Trigger 和 Bullet
      ↓
  验证健康
```

底层执行逻辑一致，但交互方式针对各自媒介优化。

## 为什么不建议 Web 直接执行 CLI 子进程

最直接的 Web 套 CLI 方式是：

```text
Web API
  → subprocess: dt resume dt-msg
  → 解析 stdout / stderr
```

如果 Web 只有少量低频按钮，这种方式可以作为早期实现；但随着 pane 观察、消息发送、多 tunnel 状态、健康恢复、Hub 所有权、技能和飞书能力增加，它会带来以下问题。

### stdout 不是稳定协议

CLI 输出首先面向人类：

```text
[ok] resumed DST dt-msg
[info] imported trigger persist JSON
```

Web 若解析这些文字，就会依赖文案、颜色控制符、输出顺序、语言和 Rich 格式。修改一条提示文字都可能破坏 Web。

### 错误信息缺少结构

CLI 常见结果只有退出码、stdout 和 stderr，而 Web 需要结构化信息：

```json
{
  "code": "hub_lock_held",
  "holder": "tm_laptop",
  "age": 42,
  "force_allowed": true
}
```

只有结构化错误才能支持“查看持有者”“稍后重试”“强制接管”等针对性界面。

### 长耗时操作难以表达阶段

`dt resume` 可能包含：

```text
claim lock
→ reconnect SSH
→ wait stable
→ probe session
→ import snapshot
→ start trigger
→ start bullet
→ verify
```

单个 CLI 子进程只提供整体生命周期，Web 很难可靠展示阶段、取消状态和中间结果。

### 并发控制更困难

多个浏览器请求可能同时启动多个 `dt` 进程。每个进程拥有独立内存锁，Web 进程内的 `threading.Lock` 无法约束其他 CLI 子进程，最终仍需统一的跨进程锁或 operation manager。

### 高频操作成本高

如果 pane 每 1.5 秒执行一次 CLI 子进程，就会反复启动 Python、导入依赖、加载配置、读取 tunnel、调用 tmux 和序列化输出。多个 tunnel 同时打开时成本明显。

### 增加安全和转义风险

若必须调用子进程，只能通过 argv：

```python
subprocess.run(["dt", "send", name, text])
```

不能拼接 shell 字符串：

```python
os.system(f"dt send {name} '{text}'")
```

即使使用 argv，仍需额外处理超时、子进程残留、输出上限和并发锁。

## “CLI 为核心”的正确体现

### CLI 是产品主入口

- 安装完成首先得到 `dt`。
- 所有关键功能都必须能从 CLI 完成。
- Web 故障时 CLI 仍然可用。
- 自动化、排障和恢复以 CLI 为权威入口。
- 高风险宿主机操作优先或只在 CLI 开放。

Web 不是 CLI 的替代品。

### CLI 首先定义操作语义

核心概念首先按照 CLI 的工作流定义：

```text
new
freeze
resume
send
drop
recover
push
pull
```

Web 不应为这些操作创建另一套不同语义。例如，Web 的 resume 不能静默变成“强制抢锁并创建新 session”。

### 成熟逻辑下沉为共享内核

参数解析、终端输出与业务操作分离：

```python
class TunnelOperations:
    def resume(self, name: str, force: bool = False) -> ResumeResult:
        ...
```

CLI 负责适配终端：

```python
def cmd_resume(args):
    result = operations.resume(args.name, args.force)
    print_resume_result(result)
```

Web 负责适配 HTTP：

```python
@router.post("/tunnels/{name}/resume")
def resume(name: str, request: ResumeRequest):
    return operations.resume(name, request.force)
```

这里的 `TunnelOperations` 或 `ControlService` 就是**可嵌入的 CLI 操作内核**。

## 推荐层次

```text
┌────────────────────────────────────────────┐
│ 产品入口                                   │
│                                            │
│  CLI             Web             Feishu   │
│  argparse        FastAPI         mailbox  │
└──────────┬──────────┬──────────────┬───────┘
           └──────────┼──────────────┘
                      ▼
┌────────────────────────────────────────────┐
│ Application Operations                     │
│                                            │
│ new / freeze / resume / send / recover     │
│ 参数校验、所有权、安全确认、操作编排       │
└──────────────────────┬─────────────────────┘
                       ▼
┌────────────────────────────────────────────┐
│ Domain / Infrastructure                    │
│                                            │
│ tmux · Hub · recovery · store · workpoint  │
│ Agent adapters · persistence integration   │
└────────────────────────────────────────────┘
```

其中：

- **入口层**处理协议和展示，不拥有核心业务规则。
- **Application Operations** 定义完整用例、权限、安全门和结果结构。
- **Domain/Infrastructure** 完成 tmux、SSH、文件、Hub 和 Agent 的具体操作。

## 当前代码所处阶段

当前项目已有部分 CLI 命令调用 `ControlService`：

```python
def cmd_send(args):
    get_control_service().send(...)
```

```python
def apply_resume(...):
    return get_control_service().resume(...)
```

但 `ControlService` 又会回调 `cli.py` 中的 `_apply_*_legacy` 实现：

```text
CLI
  → ControlService
      → cli.py 中的 legacy 实现
```

这属于迁移期结构，说明项目已经建立了共享控制面的方向，但核心生命周期逻辑尚未完全从 `cli.py` 下沉。

目标结构应为：

```text
CLI ─────┐
Web ─────┼→ TunnelOperations / ControlService
Feishu ──┘
```

`ControlService` 不应再反向依赖 `cli.py`。

## 功能范围建议

### CLI 独占或优先

- `dt config --init`
- `dt upgrade`
- `dt hotfix`
- cron 和 daemon service 安装
- 原始日志和底层诊断
- 损坏配置修复
- 强制抢占和底层恢复
- 批量脚本操作
- 开发调试命令

这些操作通常低频、影响范围较大，或者需要明确的终端上下文。

### Web 优先

- 多 tunnel 总览
- Trigger/Bullet pane 输出
- 向 pane 发送消息
- 工作标签页和最近访问
- pending/running/attention 状态
- health、sync 和 lock 状态
- 普通 freeze/resume/reconnect
- Agent capability 感知
- 事件时间线
- 面向用户的故障解释和处理建议

### 两边都支持

- list/show tunnel
- create tunnel
- send message
- freeze
- resume
- reconnect
- drop
- health probe
- recovery
- Hub push/pull

两边的差异应体现在交互方式，而不是业务语义。

## 状态边界

Web 中存在三种不同状态，必须明确区分。

### 真实业务状态

由后端掌握：

- tunnel binding
- tmux 是否存活
- session ID
- Hub owner
- health
- Agent capability
- runtime endpoint

页面刷新后必须重新读取，前端不能自行推断。

### 操作状态

由后端 operation 管理：

- resume 执行到哪一步
- recovery 是否正在退避
- Hub sync 是否失败
- 某次消息发送是否被接受

这类状态可能跨越多个 HTTP 请求，不能只依赖浏览器内的 `loading=true`。

### 纯 UI 状态

可以保存在浏览器或 Web workspace state 中：

- 当前选中的 tunnel
- op/run 切换
- 打开的标签
- 面板尺寸
- 搜索条件
- 滚动位置

纯 UI 状态不能被当作真实系统状态。

## HTTP 读写语义

GET 必须保持只读：

```text
GET  /tunnels/{name}         读取状态
POST /tunnels/{name}/resume  执行恢复
```

“选择离线 DST 自动 resume”需要谨慎处理。更清晰的流程是：

1. 页面 GET 发现 tunnel 离线。
2. 前端显示“需要恢复”。
3. 用户操作或明确配置触发 POST。
4. 页面展示恢复过程。

不应让读取页面本身隐式改变 tmux 和远端进程状态，否则浏览器刷新、预加载或多标签页可能重复执行写操作，也难以审计操作来源。

## Web 长操作的表达方式

resume、recovery 和 Hub sync 等操作应逐步支持 operation 模型：

```text
POST /api/v1/tunnels/{name}/resume
  → 202 Accepted
  → operation_id

GET /api/v1/operations/{operation_id}
SSE /api/v1/operations/{operation_id}/events
```

统一结果可以包含：

```json
{
  "ok": true,
  "operation": "session.resume",
  "data": {},
  "warnings": [],
  "audit_event": "control.session.resume",
  "request_id": "..."
}
```

这样 CLI 可以直接把阶段输出到终端，Web 则可以将相同阶段渲染成进度和状态。

## 允许 Web 调用 CLI 子进程的例外

并非所有子进程调用都必须禁止。以下低频维护操作可以选择通过 CLI 或独立进程执行：

- `dt upgrade`
- `dt hotfix`
- cron 安装
- daemon service 安装
- 独立诊断和修复脚本
- 需要严格进程隔离的维护工具

这些能力通常不应直接开放在日常 Web 工作台中。

日常高频 tunnel 操作更适合直接调用共享内核：

- list
- capture
- send
- freeze
- resume
- reconnect
- health
- recover

## 如果未来坚持 Web 完全套 CLI

若确实需要把 CLI 作为进程级机器接口，则必须正式设计稳定协议，例如：

```sh
dt --json resume dt-msg
```

至少需要满足：

- stdout 只输出单个 JSON 对象。
- 日志全部进入 stderr 或事件文件。
- 有稳定的错误码和 JSON Schema 版本。
- 禁止 ANSI/Rich 人类格式混入 stdout。
- 每个调用都有 timeout 和输出大小限制。
- 所有写操作使用跨进程锁。
- 支持 operation ID 或机器可读的进度事件。
- 参数全部通过 argv 传递，禁止拼接 shell。
- 契约测试保证版本升级不会破坏 Web。

此时架构是：

```text
React
  → Web API
      → dt --json 子进程
          → CLI application core
```

优点是进程隔离和 CLI 绝对权威；代价是性能、并发控制和进度管理更复杂。对于当前 dual-tmux，这不应成为日常 Web 操作的默认路径。

## 最终原则

> **CLI 是 dual-tmux 的核心，Web 是 CLI 能力的可视化、多任务工作台。Web 套的是 CLI 的操作内核，而不是 `dt` 可执行文件和 stdout。**

守住这一原则，可以同时获得：

- CLI-first 的产品一致性
- Web 的持续观察和交互体验
- CLI、Web、Feishu 之间唯一的业务语义
- 可测试的结构化结果和错误
- 更可靠的并发、恢复和安全边界
