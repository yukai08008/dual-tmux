# dual-tmux 机制梳理

> 配套交互式架构图：[`architecture/dual-tmux/dual-tmux-architecture.html`](architecture/dual-tmux/dual-tmux-architecture.html)
> Archify 源规格：[`architecture/dual-tmux/dual-tmux-architecture.archify.json`](architecture/dual-tmux/dual-tmux-architecture.archify.json)

## 一句话定位

dual-tmux 是一个 **Agent 工作会话编排器**：tmux 负责保持进程存活，Tunnel JSON 保存绑定和工作落点，Agent 原生 session 保存对话连续性，Hub 负责多 Client 协调。SSH 和 Docker 是 `run_*` pane 内的可重放运行环境，而不是另一套 tmux 服务。

## 核心对象

一个工作单元由两个本机 tmux session 组成：

```text
dt-myapp
├── op_myapp  → Trigger Agent
└── run_myapp → Bullet Agent + runtime endpoint
```

- `op_* / Trigger`：运行在操作者当前 Client，负责理解任务、派活、监督和恢复。
- `run_* / Bullet`：负责真正的编码、测试和工具调用，可处于本地目录、SSH Server 或 Docker 容器。
- `dt-*`：对 `op_*` 和 `run_*` 的 1:1 逻辑绑定。
- DT：已建立 tmux 对和 runtime 记录。
- DST：DT 两侧都已绑定可证明、可恢复的 Agent session。

绑定保存在 `~/.dual-tmux/tunnels/dt-<name>.json`，主要字段包括：

- `op`、`run`
- `runtime.server/container/directory/cmd`
- `trigger.tool/model/session_id`
- `bullet.tool/model/session_id`
- `op_point`、`run_point`
- Client、用户、时间戳和自动恢复配置

## Trigger 与 Bullet

Trigger 使用 tmux 把任务送入 Bullet：

```sh
tmux send-keys -t run_myapp -- '任务内容' Enter
```

两者的责任边界是：

- Bullet 负责工作目录内的编码、测试和工具调用。
- Trigger 负责宿主机操作、SSH 重连、容器创建或替换。
- Bullet 不能重建自己正在运行的容器，否则会同时杀掉自己的 pane 和 Agent 进程。

每个 Trigger 在专用目录启动：

```text
~/.dual-tmux/ops/op_myapp/
├── AGENTS.md
├── opencode.json
├── MEMORY.json
├── memory.sqlite
└── .opencode/skills/
```

`opsdir.prepare()` 会把 tunnel、Bullet pane、runtime 和 session ID 写入 Trigger 上下文，让 Trigger 启动后立即知道自己应该控制哪个 Bullet。

## 生命周期

### `dt new`

`dt new myapp` 执行以下动作：

1. 生成 `dt-myapp / op_myapp / run_myapp`。
2. 建立两个本机 tmux session。
3. 为 `run_*` 生成工作落点命令。
4. 创建 tunnel JSON 和 `entries/run_*.cmd`。
5. 为 Trigger 准备技能、配置和 `AGENTS.md`。
6. Hub 模式下上传绑定。

远程 runtime 仍由本地 `run_*` tmux 承载：

```text
本地 tmux run_myapp
    └── ssh
         └── docker exec
              └── Agent TUI
```

SSH 断开后本地 tmux 仍然存在，系统可以重新发送 `runtime.cmd`。

### `dt enter` / `dt work`

- `dt enter` 进入 Trigger pane。
- `dt work` 进入 Bullet pane。
- 两者在 Hub 模式下都会先申请 tunnel 所有权。
- 只有附带启动或 resume 参数时才启动 Agent。

### `dt freeze`

`freeze` 是 DT 转换为 DST 的关键步骤。它分别发现 Trigger 和 Bullet，并记录：

- Agent 类型、可执行文件和版本
- session ID 和 model
- Agent 所在位置：`local / ssh / docker`
- pane cwd、SSH、Docker、目录和重连 hop 链

session 归属不是通过“选择最新会话”猜测，而是结合：

- tmux pane PID 和子进程树
- Agent 命令行中的显式 session ID
- 进程启动时间
- 当前目录
- OpenCode sqlite 或 Codex/Claude 原生 session 文件
- 远程 `/proc` 进程信息

只有能证明属于当前 pane 的 session 才会绑定；候选不唯一时 freeze 失败，不会猜测历史会话。两侧均有有效 `session_id` 时才是 DST。

### `dt resume`

恢复顺序是：

1. 申请 Hub 锁。
2. 验证绑定确实是 DST。
3. 创建缺失的本机 tmux session。
4. 对远程 Bullet 重放 `runtime.cmd`。
5. 等待 SSH/Docker 连接稳定，拒绝在瞬时连接上发送 session 命令。
6. 检查目标环境内是否存在原 session。
7. 必要时从 persist JSON 导入。
8. Trigger 和 Bullet 在各自实际位置执行原生 resume。
9. 更新工作点和时间戳。

原生恢复命令类似：

```text
OpenCode    opencode --auto -s <session_id>
Codex       codex resume <uuid>
Claude      claude --resume <uuid>
```

## 工作点发现

`run_*` 可能经过多层 hop：

```text
本地 shell → SSH alias → Server → docker exec → 工作目录
```

系统从两类证据重建 runtime：

1. pane 进程树：识别 `ssh`、`docker exec` 和 Agent。
2. pane scrollback：解析 shell prompt 的主机、目录和上一条命令，重建 hops。

最终工作点包含 `kind`、`ssh`、`container`、`directory`、`resume_cmd` 和 `hops`。裸 shell alias 会先展开成真实 SSH 命令，再提取主机和端口。

## 会话数据的一致性模型

### Trigger：跟随操作者

Trigger 总在当前 Client 运行。换机器后，新 Client 的 Agent 存储里通常没有原 session，因此需要：

```text
旧 Client sqlite
    → dt tick 导出 JSON
    → persist tree / Hub
    → 新 Client 拉取
    → dt resume 导入本地 Agent store
```

### 远程 Bullet：固定在工作落点

远程 Bullet 的 Agent store 位于 Server 或容器。Client 不复制这份存储，而是重放同一个 `runtime.cmd`，返回同一个 session 的唯一真源。

| 数据 | 位置 | dual-tmux 是否同步 |
|---|---|---|
| tunnel binding、runtime entry | Client + Hub | 是 |
| Trigger/本地 Bullet 会话 JSON | persist tree | 间接配合 |
| 远程 Bullet Agent store | Server/容器 | 否 |
| tmux 实时进程 | Client tmux server | 否 |

简化后就是：**Trigger 数据随人走，远程 Bullet 则由人回到数据所在地。**

## Hub 同步与所有权

Hub 不是必须常驻的应用服务，核心是 SSH 可访问的文件树：

```text
~/<user>/dual-tmux/
├── tunnels/
├── entries/
├── locks/
└── activity/
```

### 合并同步

1. 将 Hub 快照下载到临时目录。
2. 合并本地和 Hub 的 tunnel 集合。
3. tunnel 按 `updated_at` 选择较新版本，同时间用内容哈希稳定决胜。
4. runtime entry 跟随所属 tunnel 的胜者。
5. 把合并结果同时写回本地和 Hub。

这是整文件级的 Last-Writer-Wins，不是字段级 CRDT。普通 merge 不传播删除，避免网络异常或空快照造成误删。

### 单 Client 所有权

每个 tunnel 在 Hub 上有锁文件：

```text
<client>@<epoch>@<generation>
```

- `enter/work/resume` 先 claim。
- 锁 TTL 为 300 秒，`dt tick` 持续刷新。
- 其他 Client 不能直接进入活跃 tunnel。
- 若原 Client 最近 30 个 tick 的 pane 指纹均未变化，允许接管。
- `--force` 可显式抢占。
- 发现所有权属于其他 Client 时，本地旧 `op_* / run_*` 会被清理。

## `dt tick` 后台心跳

`dt tick` 通常每分钟运行，其职责包括：

```text
检查 Hub 所有权
  → 清理非本机所有的 pane
  → 记录 pane 活动指纹
  → 刷新 tunnel 锁
  → 执行分层健康检查
  → 按需导出 Trigger/本地 Bullet 快照
  → Hub merge-sync
  → 刷新 tmux 状态栏
  → 消费飞书 mailbox
```

因此 tick 既是心跳，也是所有权、持久化、健康恢复和飞书离线补偿的统一时钟。

## 健康检查和自动恢复

系统检查的是结构性证据，而不是“pane 多久没变”：

- Trigger/Bullet tmux 是否存在
- Agent 是否运行
- `run_*` 是否仍维持 SSH/Docker
- SSH 是否可达
- 容器是否运行
- 工作目录是否存在
- session 是否确实存在于对应存储

自动恢复默认关闭，需按 tunnel 开启。连续 3 次结构性失败后才恢复，失败退避为 60、120、300、600、1800 秒；5 次失败后进入 `attention` 断路状态。恢复最终复用正常 resume 链路，不猜容器、不清 session ID、不改写最后健康工作点。

## 统一控制面

CLI、Web 和飞书逐步收敛到 `ControlService`：

```text
CLI / Web / Feishu
        ↓
   ControlService
        ↓
Agent capability registry + tmux + Hub + recovery
```

操作契约声明所需 Agent capability、风险级别、支持入口和审计事件。OpenCode 支持 start/freeze/resume/model，Codex 和 Claude Code 支持 start/freeze/resume；不支持的能力由控制层拒绝。

飞书远程命令使用持久 mailbox：Hub daemon 通过官方 WebSocket 接收事件，写入请求 envelope；目标 Client daemon 轮询 mailbox，执行 ControlService 操作并写回响应。目标 Client 睡眠时命令可保留，`dt tick` 还提供一分钟级补偿。

## 设计优点与当前风险

优点：

- tmux、Agent session、persist JSON 和 Hub binding 职责分离。
- freeze 优先证明 session 归属，避免恢复错会话。
- Trigger 迁移、Bullet 固定工作点的一致性模型符合实际数据位置。
- Hub 不需要复杂的常驻服务，只依赖 SSH、rsync 和 flock。
- 健康恢复基于结构失败，不会把正常空闲当故障。

当前风险：

- `cli.py` 生命周期、UI 和兼容逻辑较集中。
- `ControlService` 仍回调 `_apply_*_legacy`，属于迁移期双向依赖。
- Tunnel JSON 是整文件 Last-Writer-Wins，不同 Client 并发修改不同字段时可能丢更新。
- 部分状态文件是直接写入，尚未统一使用临时文件加原子 rename。
- 工作点发现依赖 shell prompt 和 scrollback，不同主题、alias 和历史输出会增加推断难度。
- `dt tick` 同时承担所有权、健康、快照、Hub 同步、状态栏和飞书补偿，长期可拆成独立 job。

## 结论

dual-tmux 用 tmux 保存“进程壳”，用 Agent session 保存“思考上下文”，用 runtime/workpoint 保存“工作地点”，用 Hub 锁保存“谁有权操作”，再通过 freeze/resume 把它们组合成可跨机器接管的长期 Agent 工作单元。
