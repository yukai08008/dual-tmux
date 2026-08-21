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
└── entries/run_<name>.cmd    # run_* 回连命令
```

若你另外做 tmux / OpenCode 持久化（可选、另一套工具），那些树 **不是** dual-tmux 的：

| 谁 | 路径 | 规则 |
|----|------|------|
| 本 CLI | `~/.dual-tmux/` | 隧道登记 + 跳板命令 |
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

## 用法

```sh
dt --version
dt doctor

dt new myapp                  # 只有 DT：op_* + run_*
dt enter myapp                # op 会话
dt work  myapp                # run 会话
dt enter myapp --oc --model glm-5.1
dt work  myapp --oc --model glm-5.1
dt freeze myapp               # 两侧都有 oc 才算 DST
dt ls                         # DT | IS_DST | ...

dt make dst myapp --model glm-5.1    # 一键 DT + 两侧 oc + freeze
dt resume myapp                      # 掉了的 oc 自动接上
```

`dt new` 只建 **DT**。**DST** 要等 op 和 run 下面都有 oc 会话（`tool` + `model` + `session_id`）。`dt ls` 第一列 DT，第二列 IS_DST。

`run_*` 是**本机跳板会话**。pane 里 ssh（可选再 `docker exec`）进入 Server 工作目录。默认不要在 Server 上再套一层 tmux。

## 命令

| 命令 | 作用 |
|------|------|
| `dt` / `dt enter` | 接入线头会话 op_* |
| `dt work` | 接入工作区跳板 run_* |
| `dt re` | 重新打入跳板命令 |
| `dt new` | 创建会话并登记 |
| `dt ls` | DT 名 + IS_DST |
| `dt freeze` | 冻结两侧 oc；两边都有才是 DST |
| `dt make dst` | 建 DT、起两侧 oc、freeze |
| `dt resume` | 接续 DST；oc 掉了会自动接 |
| `dt enter --oc --model` | 起 trigger oc |
| `dt work --oc --model` | 起 bullet oc |
| `dt send` | 向 `run_*` 发送 `tmux send-keys` |
| `dt doctor` | 检查 Client tmux 和到 Server 的 ssh（不改 SSH） |
| `dt config --init` | 写入 `tm_*` 本机源名 + ssh Host + user |
| `dt upgrade` | `uv tool upgrade dual-tmux` |

## 卸载

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```

卸载只删 `dt` 可执行文件。`~/.dual-tmux/` 保留。tmux 会话、OpenCode 库、`~/sessions/` 都不动。
