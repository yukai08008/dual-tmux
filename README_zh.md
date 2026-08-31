# dual-tmux

[English](README.md) · [Persist 同步](docs/persist-sync.md)

双层 tmux 隧道。物理会话仍是普通 tmux；本 CLI 给它们命名，并按 1:1 绑定。dual-tmux 有两种基础运行模式：**纯本地模式**与 **Hub 同步模式**。

```
Client（本机）
  op_<name>          trigger agent（默认 OpenCode）
       │  dt-<name>
  run_<name>         本地工作目录，或 ssh / docker exec → Server 工作目录
                          └─ bullet agent（默认 OpenCode）
```

**Client** 是你坐的那台机器。**Server / Hub** 是可选的；配置后，它既是新隧道的默认 SSH 工作目标，也是隧道记录的同步中心。dual-tmux 不保存任何密钥。

## 基础运行模式

这是贯穿项目的持久运行模型，不只是首次安装选项。每台 Client 在任意时刻只处于以下一种模式：

| 模式 | 必需配置 | 新隧道运行位置 | 隧道记录 | 网络与占用锁 |
|---|---|---|---|---|
| **纯本地模式** | `client` | 本机工作目录，默认当前目录 | 只保存在本机 `~/.dual-tmux/` | 不执行 SSH、rsync、Hub push/pull 或分布式锁 |
| **Hub 同步模式** | `client` + `server` + `user` | 默认进入 `server` 的 `/workspace`，仍可按隧道覆盖 | 本机副本 + Hub 的 `~/<user>/dual-tmux/` | 自动合并同步，并使用单 Client 占用锁 |

纯本地模式是完整可用的基础模式：不配置服务器也可以创建、进入、工作、freeze、resume 和管理本地隧道。Hub 模式在此基础上增加跨 Client 发现、同步、接管保护和远端 persist 集成；它不是基本使用的前置条件。

## 健康检测与断线恢复

`dt tick` 会分层记录 tmux、SSH transport、已登记的容器与目录、Agent 进程和 OpenCode session 健康状态。画面长期不变不会被当作故障：仅凭 pane 静止无法区分正常空闲与 freeze，因而不会触发重启。

自动恢复默认按隧道关闭，需要显式开启：

```sh
dt health myapp --json          # 立即探测并更新本地缓存
dt recover myapp --enable       # 仅为这条隧道开启
dt recover myapp --status       # 读取缓存状态
dt recover myapp --now          # 取得 Hub 所有权后立即恢复
dt recover myapp --disable
```

连续三次结构性失败才自动恢复；失败后依次退避 60、120、300、600、1800 秒，五次失败进入 `attention` 并熔断。SSH runtime 使用 `15 秒 × 3 次` keepalive，让死连接退出并把控制权交还本机 tmux。恢复不会猜容器名、清空 session id、删除 persist JSON 或改写最后健康工作点。Web 和 `GET /api/health` 只读缓存，浏览器请求绝不会直接触发 SSH probe。

用户可以随时切换模式：

```sh
# 从纯本地开始
dt config --init --local --client tm_laptop

# 首次接入 Hub，或更换当前 Hub
dt config --server tom7r --user andy

# 最后合并一次，再回到纯本地模式
dt config --local
```

切换遵循“先合并、后提交配置”：存在旧 Hub 时先合并旧 Hub；接入或更换时再合并候选 Hub；所有必要同步成功后才原子写入 `config.toml`。SSH/rsync 失败时，原模式和原配置保持不变。切换不会改写已有隧道的 `runtime`，只会改变同步行为以及以后新建隧道的默认值。合并过程永不传播删除。

## 第一次启动

安装会把 `dt` 放进 PATH，并加上每分钟 crontab（`dt tick`）。请选择一种基础运行模式。纯本地隧道默认使用当前目录；Hub 模式的跳板目录默认 `/workspace`，某条隧道要用别的路径再 `dt new --dir`。

| 字段 | 你填什么 | 本 CLI **不会**做的 |
|------|----------|---------------------|
| `client` | 合规的**本机源主机名**：`tm_` + `[A-Za-z0-9._-]`。例：`tm_laptop`。不要用 hostname。 | 不会用 `hostname` 瞎起名 |
| `server` | 可选的同步中心，也是新隧道的默认跳板；只要 `ssh` 能通。 | 不写 `~/.ssh/config`、密钥、`known_hosts`。 |
| `user` | 与 `server` 成对填写。人名：`[A-Za-z][A-Za-z0-9._-]`。例：`ouc`。 | 不创建系统账号 |

```sh
dt config --init --local --client tm_laptop  # 不依赖服务器

# 或初始化时直接配置中心（旧命令继续兼容）
dt config --init --client tm_laptop --server myserver --user ouc
ssh myserver          # 必须已经能通
dt doctor
```

纯本地模式的 `~/.dual-tmux/config.toml`：

```toml
client = "tm_laptop"
workspace = "/path/to/my-project"
```

Hub 模式的 `~/.dual-tmux/config.toml`：

```toml
client = "tm_laptop"   # 本机源名
server = "myserver"    # ~/.ssh/config 里的 Host
user = "ouc"           # 人；远端 persist 在 ~/<user>/sessions
workspace = "/workspace"  # 默认跳板目录；初始化不问
```

没有配置时，`dt` 会在 TTY 里询问纯本地或 Hub 模式。纯本地只检查 Client 运行环境；Hub 模式还会检查 `ssh <server>`。SSH 始终由你自己管。

另外：Client 必须已装 tmux。`op_*` / `run_*` 都是**本机会话**；`run_*` 只通过 ssh 进 Server。

## 占用的目录

本 CLI 只占用 `~/.dual-tmux/`（可用 `DUAL_TMUX_HOME` 覆盖），不写 `~/sessions`。

```
~/.dual-tmux/                 # 仅 dual-tmux
├── config.toml               # client + server + workspace
├── tunnels/dt-<name>.json    # op/run 1:1 绑定
├── entries/run_<name>.cmd    # run_* 回连命令
├── events.jsonl              # CLI 事件 / 操作日志
├── skills/                   # 从安装包同步出来的 trigger 技能
└── ops/op_<name>/AGENTS.md   # trigger OpenCode 的启动目录
```

## Hub 模式下由另一台 Client 接续 DST

这是 **第三棵树**，和 tmux persist、OpenCode persist 不冲突。

| 树 | 路径 | 管什么 |
|----|------|--------|
| tmux persist | `~/sessions/tmux/tm_*/` | 窗口 / 进程 / 屏幕 |
| OpenCode persist | `~/sessions/opencode/tm_*/` | 对话 JSON |
| **dt 枢纽** | Server `~/<user>/dual-tmux/` | 只存 DT/DST 绑定 |

Hub 模式的同步是 **自动的**：`new` / `freeze` / `bind` / `enter` / `work` / `resume` 会后台推送；每分钟 `dt tick` 会按 `updated_at` 合并本机与中心的 `tunnels/` + `entries/`，所以另一台 Client 新建的隧道会自动出现。`dt push` / `dt pull` 用于要求立即单向同步。纯本地模式不会执行网络同步和分布式锁操作。不拷 `config.toml`、`ops/`、`events.jsonl`。

```sh
# 另一台 —— tick 会自动发现；要立刻接续可手动 pull
dt pull && dt resume dt-msg
```

另一台机器：

```sh
uv tool install git+https://github.com/yukai08008/dual-tmux.git
dt config --init --client tm_<那台> --server tom7r --user andy
ssh tom7r    # 必须已经能通；dt 不写 ~/.ssh
dt pull
dt resume dt-msg              # import trigger JSON，再 -s；bullet 在跳板对端 -s
```

`dt pull` 只恢复绑定。`dt resume` 会把 **trigger** 的 persist JSON import 进本机 sqlite，再在 `op_*` 里 `opencode --auto -s <id>`。远端 bullet 会重放 `runtime.cmd`，等待跳板稳定后在目标 sqlite 执行 `-s`；纯本地 bullet 则把 JSON 导入 Client sqlite。见 [docs/persist-sync.md](docs/persist-sync.md)。

同一时刻只有一台 Client：枢纽锁 `~/<user>/dual-tmux/locks/<dt-名>`（`client@epoch`，TTL 300s）。`enter` / `work` / `resume` 占锁。

闲置不看 TTL。`dt tick` 每分钟打指纹。另一台 `dt resume` 在近 **30 个 tick** 冻住时接管。旧 Client 上的 `op_*`/`run_*` **直接杀掉**（不留 `__parked`）。绑定在枢纽，对话在 persist，下次 `dt resume` 再起一套很轻的 tmux。现在放手：`dt drop dt-msg`。抢：`--force`。

要 **分叉**（两条隧道同时活，不是抢锁）：

```sh
dt branch dt-msg dt-msg-v2
```

会 **重放** 记下的跳板（`runtime.cmd` 或 hops：ssh → docker → cwd），两侧用同样 model **新开** oc（新 `session_id`），再 freeze 成自己的 DST。源 `dt-msg` 的锁和现场不动。同一容器可以进两次；不要复用父会话的 oc id。

安装 / `dt doctor` / `dt upgrade` 会写 tick crontab，并打 persist 租户 hotfix（`~/<user>/sessions`）。另一台同一条一键安装后 `dt pull && dt resume`。

trigger oc 从 `ops/op_*` 启动，必读 `AGENTS.md`，里面指向包内的 `dual-tmux` + `tmux-trigger`。任意机器 `uv tool install` 后布局相同。

把 `dt` 当成一个小 server：每条命令往 `events.jsonl` 追加一行（`cmd.start` / `cmd.ok` / `cmd.fail`，以及 `freeze.start` / `freeze.side.ok` / `freeze.side.fail` / `freeze.ok`）。`dt log` 用来回溯。freeze 失败也是事件，不只是一行 stderr。

若你另外做 tmux / OpenCode 持久化（可选、另一套工具），那些树 **不是** dual-tmux 的：

| 谁 | 路径 | 规则 |
|----|------|------|
| 本 CLI | `~/.dual-tmux/` | 隧道登记 + 跳板命令 |
| dt 枢纽（Server） | `~/<user>/dual-tmux/{tunnels,entries}` | `dt push` / `dt pull`；不是 persist |
| tmux persist（Client） | `~/sessions/tmux/<tm_来源>/` | 来源目录必须 `tm_*` |
| tmux persist（Server） | `~/<user>/sessions/tmux/<tm_来源>/` | 同一棵树，按人隔离 |
| OpenCode persist（Client） | `~/sessions/opencode/<tm_来源>/` | 与 tmux 同一套 `tm_*` 源名 |
| OpenCode persist（Server） | `~/<user>/sessions/opencode/<tm_来源>/` | 同一棵树，按人隔离 |
| OpenCode 活库 | `~/.local/share/opencode/opencode.db` | 禁止 rsync 整库 |
| OpenCode 配置 | `~/.config/opencode/` | 模型/凭据，本 CLI 不管 |
| tmux 活会话 | 进程内存 + `/tmp/tmux-*` socket | 不是本 CLI 的文件 |
| ssh | `~/.ssh/` | 你的；永不改写 |

`client` 是机器源名 `tm_*`。`user` 是人。多人共用一台 Server 时每人一个 `user`：本地仍是 `~/sessions`，远端是 `~/<user>/sessions`。

## Agent 客户端与控制架构

dual-tmux 能识别 trigger 和 bullet pane 中的 OpenCode、Codex 与 Claude Code。客户端支持采用能力模型：仅仅能检测可执行文件和版本，不代表该客户端已经能恢复会话。

| 能力 | OpenCode | Codex | Claude Code |
|---|---:|---:|---:|
| 检测可执行文件和版本 | 是 | 是 | 是 |
| 采集本地 / SSH / Docker 元数据 | 是 | 是 | 是 |
| 通过 tmux pane 发送文本 | 是 | 是 | 是 |
| `freeze` 时记录客户端元数据 | 是 | 是 | 是 |
| 启动并冻结可恢复的原生会话 | 是 | 是 | 是 |
| 恢复冻结的原生会话 | 是 | 是 | 是 |
| 由 dual-tmux 切换模型 | 是 | 尚未 | 尚未 |

已经迁移的 CLI 与 Web 操作共用同一控制合同：

```text
CLI / Web / 未来飞书
          ↓
    ControlService
          ↓
Agent 能力注册表 + tunnel/tmux 操作
```

本地 Web API 提供 `GET /api/capabilities` 和 `GET /api/operations`，供调用方查询能力与操作目录。原生生命周期发现采用保守规则：Codex/Claude 优先读取活动进程显式携带的 session UUID；否则会话文件必须同时唯一匹配 pane 工作目录与进程启动时间。候选含糊或只有历史记录时拒绝绑定，不猜最新会话。

v0.4.46 Web 控制面覆盖日常 tunnel 全闭环：创建本地/Hub tunnel、两侧客户端选择、pane 输入输出、freeze/resume、权威入口重连、drop/删除、Hub push/pull、健康检查/恢复、自动恢复开关，以及无损的本地/Hub 模式切换。破坏性操作必须显式确认。主机维护命令（`upgrade`、`hotfix`、cron 安装）仍只允许从 CLI 执行，并在 Web 指南中给出入口。

v0.4.48 使用飞书官方的 scan-to-create Device Registration。用户不需要提供 App ID、App Secret、verification token 或公网 callback：Web 展示一次性二维码，飞书自动创建 PersonalAgent，dual-tmux 自动加密保存生成的凭据。`dt daemon` 独立于 `dt web` 持有出站 WebSocket，重启后自动恢复并监督重连。详见 [飞书扫码即用](docs/feishu.md)。

## 默认 agent：OpenCode

`op_*`（trigger）和 `run_*`（bullet）默认给 **[OpenCode](https://opencode.ai)** 会话用。

这是寿命选择：OpenCode 是开源的。绑死闭源 CLI（密钥、私有会话库、协议说变就变）是这类隧道一年后报废的常见原因。dual-tmux 只给 tmux 起名和 `tmux send-keys`；agent 可换，但文档默认 OpenCode，少踩私有工具的坑。

OpenCode 请自行安装。本 CLI 不内置。

## 前提

1. `ssh <server>` 已经能通（Host 别名 + 你自己的密钥）。
2. Client 已安装 tmux。
3. Server 上已有工作目录（若使用 `--container`，容器内也要有）。
4. 走默认 trigger/bullet 流程时，已安装 OpenCode。

## 安装

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash
```

或用 uv：

```sh
uv tool install git+https://github.com/yukai08008/dual-tmux.git
```

## 命令流

```
DT  = op tmux + run tmux
DST = DT + op-oc + run-oc   （两侧 oc 都 freeze 才算）
```

```
dt new myapp
        │
        ├─ dt enter myapp              op tmux
        │       └─ --oc [--model M]    起 trigger OpenCode
        │
        ├─ dt work myapp               run tmux
        │       └─ --oc [--model M]    起 bullet OpenCode
        │
        ├─ dt freeze myapp             记下两侧 oc（tool/model/session_id）
        │                              两边都有 oc 才 IS_DST=yes
        │
        ├─ dt ls                       第 1 列 DT，第 2 列 IS_DST
        │
        ├─ dt make dst myapp [--tool opencode] [--model M]
        │                              一键：new + 两侧 oc + freeze
        │
        └─ dt resume myapp             掉了的 op-oc / run-oc 自动接上，再 attach
```

逐步：

```sh
dt doctor

dt new myapp                          # 只有 DT
dt enter myapp                        # 进 op_*
dt work  myapp                        # 进 run_*
dt enter myapp --oc --model glm-5.1   # 在 op 里起 oc
dt work  myapp --oc --model glm-5.1   # 在 run 里起 oc
dt freeze myapp                       # 冻结两侧；两边都有才是 DST
dt ls                                 # DT | IS_DST | OP | RUN | TRIGGER | BULLET

dt make dst myapp --model glm-5.1     # 一条命令得到同样结果
dt resume myapp                       # oc 掉了 → 自动 --auto -s <id>
dt send myapp '发给 bullet 的任务'
```

`dt new` 不会创建 DST。`--oc` 可以不带 `--model`（用 harness 默认模型）。手工 `--oc` 之后必须 `dt freeze`。接续 DST 用 `dt resume`。

每侧冻结后记下 `tool`、`model`、`session_id`，以及 `agent_client`（客户端名、版本、原始版本输出、可执行文件、local/ssh/docker 位置和采集时间）。OpenCode、Codex 与 Claude Code 均支持原生 freeze/resume。远端 pane 只显示 ssh 时可用 `dt freeze --tool codex|claude` 明确指定。恢复始终沿用冻结 ID，分别执行 `opencode --auto -s <id>`、`codex resume <uuid>` 或 `claude --resume <uuid>`，不会退化为未经证明的“最新会话”。

freeze 还会记下 **工作点**（`op_point` / `run_point`：kind、cwd、ssh、docker、resume_cmd）和 **时间**（`created_at`、`enter_at`、`work_at`、`freeze_at`、`resume_at`）。一侧失败不会丢掉另一侧。`dt inspect` 能看到这些。

`run_*` 是**本机跳板会话**。pane 里 ssh（可选再 `docker exec`）进入 Server 工作目录。默认不要在 Server 上再套一层 tmux。

## 命令

| 命令 | 作用 |
|------|------|
| `dt new <name>` | 只建 **DT**（`op_*` + `run_*`） |
| `dt branch <src> <dest>` | 重放跳板，两侧**新** oc，freeze 成自己的 DST |
| `dt rm <name> [-y] [--kill]` | 注销 DT；`--kill` 同时杀掉 op_*/run_* tmux |
| `dt enter <name>` | 接入 op tmux |
| `dt work <name>` | 接入 run tmux |
| `dt enter --oc [--model M]` | 在 op 里起 trigger oc |
| `dt work --oc [--model M]` | 在 run 里起 bullet oc |
| `dt freeze <name>` | 冻结两侧 oc；两边都有才是 **DST** |
| `dt model <name> [--run|--op] <id>` | 退出该侧 oc，用新模型再起，freeze |
| `dt ls` | 第 1 列 DT，第 2 列 IS_DST |
| `dt make dst <name> [--tool] [--model]` | 一键 DT + 两侧 oc + freeze |
| `dt resume <name> [--force]` | 接续 DST；`--force` 抢枢纽锁 |
| `dt drop <name>` | 杀掉本机 op_*/run_* 并放锁；枢纽绑定保留 |
| `dt tick` | 每分钟任务（安装 / doctor 会加 crontab） |
| `dt cron [--remove]` | 安装或去掉 tick crontab |
| `dt push` | 立刻推（平时 freeze/new/work 已后台推） |
| `dt pull` | 从枢纽拉 tunnels+entries；不覆盖本机 `client` |
| `dt re <name>` | 重新打入 run_* 的 ssh/docker |
| `dt send <name> '…'` | 向 run_*（bullet）发 `tmux send-keys` |
| `dt inspect <name>` | 查看 DT 以及 op/run 的 tool、model、session_id（可空） |
| `dt log [-n] [--kind freeze] [--name dt-msg]` | CLI 事件日志 |
| `dt show <name>` | 隧道 JSON |
| `dt` | 接入最近一条 op_* |
| `dt doctor` | 检查 Client tmux 和可选 Hub；校准 persist 同步 |
| `dt config --init [--local]` | 初始化纯本地或 Hub 模式 |
| `dt config --server H --user U` | 无损接入或更换 Hub |
| `dt config --local` | 最后合并后安全退出 Hub |
| `dt upgrade` | `uv tool upgrade dual-tmux`，然后打 persist 租户 hotfix |

## 卸载

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```

卸载只删 `dt` 可执行文件。`~/.dual-tmux/` 保留。tmux 会话、OpenCode 库、`~/sessions/` 都不动。
