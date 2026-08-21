# dual-tmux

[English](README.md)

双层 tmux 隧道。物理会话仍是普通 tmux；本 CLI 给它们命名，并按 1:1 绑定。

```
Client（本机）
  op_<name>          trigger agent（默认 OpenCode）
       │  dt-<name>
  run_<name>         ssh / docker exec → Server 工作目录
                          └─ bullet agent（默认 OpenCode）
```

**Client** 是你坐的那台机器。**Server** 是干活的 ssh 主机（容器可选）。dual-tmux 不保存任何密钥。

## 第一次启动

安装只是把 `dt` 放到 PATH。第一次真正干活（`dt` / `dt new` / `dt work` / `dt config --init`）收 **三个字段**。跳板目录默认 `/workspace`，某条隧道要用别的路径再 `dt new --dir`。

| 字段 | 你填什么 | 本 CLI **不会**做的 |
|------|----------|---------------------|
| `client` | 合规的**本机源主机名**：`tm_` + `[A-Za-z0-9._-]`。例：`tm_laptop`。不要用 hostname。 | 不会用 `hostname` 瞎起名 |
| `server` | 只要 `ssh` 能通。粘贴 `ssh -p 22 root@IP`：若 `~/.ssh/config` 有对应 Host 就记别名，否则记 `root@IP`。名字好不好看无所谓。 | 不写 `~/.ssh/config`、密钥、`known_hosts`。不用远端 hostname。 |
| `user` | 人名：`[A-Za-z][A-Za-z0-9._-]`。例：`ouc`。不要 `tm_*`。 | 不创建系统账号 |

```sh
dt config --init --client tm_laptop --server myserver --user ouc
ssh myserver          # 必须已经能通
dt doctor
```

`~/.dual-tmux/config.toml`：

```toml
client = "tm_laptop"   # 本机源名
server = "myserver"    # ~/.ssh/config 里的 Host
user = "ouc"           # 人；远端 persist 在 ~/<user>/sessions
workspace = "/workspace"  # 默认跳板目录；初始化不问
```

没有配置时，`dt` 会在 TTY 里问这三项，然后检查 Client tmux 和 `ssh <server>`。SSH 始终由你自己管。

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

## 另一台 Client 接续 DST

这是 **第三棵树**，和 tmux persist、OpenCode persist 不冲突。

| 树 | 路径 | 管什么 |
|----|------|--------|
| tmux persist | `~/sessions/tmux/tm_*/` | 窗口 / 进程 / 屏幕 |
| OpenCode persist | `~/sessions/opencode/tm_*/` | 对话 JSON |
| **dt 枢纽** | Server `~/<user>/dual-tmux/` | 只存 DT/DST 绑定 |

`dt push` / `dt pull` **只** rsync `tunnels/` 和 `entries/`。不推 `config.toml`（这台机的 `client`）、`ops/`、`events.jsonl`。`new` / `freeze` / `bind` 会尽力推。

这台笔记本（freeze 之后已经做过）：

```sh
dt push
```

另一台机器：

```sh
uv tool install git+https://github.com/yukai08008/dual-tmux.git
dt config --init --client tm_<那台> --server tom7r --user andy
ssh tom7r    # 必须已经能通；dt 不写 ~/.ssh
dt pull
# 若那台机 oc sqlite 是空的，先 oc-restore persist 里
# trigger/bullet 的 JSON（~/sessions/opencode/tm_*/<slug>.json）
dt resume dt-msg
```

`dt pull` 只恢复绑定。`dt resume` 在 `op_*` / `run_*` 里跑 `opencode --auto -s <id>`。没做 persist restore 时 `-s` 会 Session not found。每台 Client 的 `config.toml` 仍用自己的 `tm_*`。

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

每侧冻结后记下 `tool`（默认 `opencode`）、`model`、`session_id`。接续用 `opencode --auto -s <id>`，禁用 `-c`。

freeze 还会记下 **工作点**（`op_point` / `run_point`：kind、cwd、ssh、docker、resume_cmd）和 **时间**（`created_at`、`enter_at`、`work_at`、`freeze_at`、`resume_at`）。一侧失败不会丢掉另一侧。`dt inspect` 能看到这些。

`run_*` 是**本机跳板会话**。pane 里 ssh（可选再 `docker exec`）进入 Server 工作目录。默认不要在 Server 上再套一层 tmux。

## 命令

| 命令 | 作用 |
|------|------|
| `dt new <name>` | 只建 **DT**（`op_*` + `run_*`） |
| `dt rm <name> [-y] [--kill]` | 注销 DT；`--kill` 同时杀掉 op_*/run_* tmux |
| `dt enter <name>` | 接入 op tmux |
| `dt work <name>` | 接入 run tmux |
| `dt enter --oc [--model M]` | 在 op 里起 trigger oc |
| `dt work --oc [--model M]` | 在 run 里起 bullet oc |
| `dt freeze <name>` | 冻结两侧 oc；两边都有才是 **DST** |
| `dt ls` | 第 1 列 DT，第 2 列 IS_DST |
| `dt make dst <name> [--tool] [--model]` | 一键 DT + 两侧 oc + freeze |
| `dt resume <name>` | 接续 DST；oc 掉了自动接 |
| `dt push` | 把 tunnels+entries 推到 Server `~/<user>/dual-tmux` |
| `dt pull` | 从枢纽拉 tunnels+entries；不覆盖本机 `client` |
| `dt re <name>` | 重新打入 run_* 的 ssh/docker |
| `dt send <name> '…'` | 向 run_*（bullet）发 `tmux send-keys` |
| `dt inspect <name>` | 查看 DT 以及 op/run 的 tool、model、session_id（可空） |
| `dt log [-n] [--kind freeze] [--name dt-msg]` | CLI 事件日志 |
| `dt show <name>` | 隧道 JSON |
| `dt` | 接入最近一条 op_* |
| `dt doctor` | 检查 Client tmux 和 ssh（不改 SSH） |
| `dt config --init` | 写入 client + server + user |
| `dt upgrade` | `uv tool upgrade dual-tmux` |

## 卸载

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```

卸载只删 `dt` 可执行文件。`~/.dual-tmux/` 保留。tmux 会话、OpenCode 库、`~/sessions/` 都不动。
