# dual-tmux

[English](README.md)

双层 tmux 隧道。物理会话仍是普通 tmux；本 CLI 给它们命名，并按 1:1 绑定。

```
Client（本机）
  op_<name>          trigger agent
       │  dt-<name>
  run_<name>         ssh / docker exec → Server 工作目录
                          └─ bullet agent
```

**Client** 是你坐的那台机器。**Server** 是干活的 ssh 主机（容器可选）。dual-tmux 不保存任何密钥。

本机数据在 `~/.dual-tmux/`（可用 `DUAL_TMUX_HOME` 覆盖）。

## 前提

使用本 CLI 之前：

1. Client 上已经能 `ssh <server>`（`~/.ssh/config` 的 Host 别名 + 密钥登录）。
2. **Client 已安装 tmux。** `op_*` / `run_*` 都是本机会话；`run_*` 只通过 ssh 进 Server。
3. Server 上已有工作目录（若使用 `--container`，容器内也要有）。

本工具不负责配置 SSH、密钥或远端 tmux。`dt doctor` 会检查 Client 的 tmux 以及 `ssh <server>`。

## 安装

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash
```

或用 uv：

```sh
uv tool install git+https://github.com/yukai08008/dual-tmux.git
```

## 初始化

```sh
dt config --init --client laptop --server myserver
dt doctor
```

`~/.dual-tmux/config.toml`：

```toml
client = "laptop"      # 本机身份
server = "myserver"    # ~/.ssh/config 里的 Host
workspace = "/workspace"
```

`run_*` 是**本机跳板会话**。pane 里 ssh（可选再 `docker exec`）进入 Server 工作目录。默认不要在 Server 上再套一层 tmux。

## 用法

```sh
dt --version
dt doctor

dt new myapp --container appbox --dir /workspace/myapp
dt ls
dt show dt-myapp

dt enter dt-myapp     # 接入 op_*
dt work  dt-myapp     # 接入 run_*
dt re    dt-myapp     # 跳板掉回本机 shell 时，重新打入 ssh/docker

dt bind dt-myapp --trigger trigger-slug --bullet bullet-slug
dt send dt-myapp '发给 bullet agent 的任务'

dt                    # 接入最近一条隧道的 op_*
```

`dt new NAME` 会展开成 `dt-NAME` / `op_NAME` / `run_NAME`。一条隧道只绑一对 op 和 run。

```
~/.dual-tmux/
├── config.toml
├── tunnels/dt-<name>.json
└── entries/run_<name>.cmd
```

## 命令

| 命令 | 作用 |
|------|------|
| `dt` / `dt enter` | 接入线头会话 op_* |
| `dt work` | 接入工作区跳板 run_* |
| `dt re` | 重新打入跳板命令 |
| `dt new` | 创建会话并登记 |
| `dt ls` / `dt show` | 查看 |
| `dt bind` | 绑定 trigger/bullet 会话 slug |
| `dt send` | 向 `run_*` 发送 `tmux send-keys` |
| `dt doctor` | 检查本机环境 |
| `dt config --init` | 写入 Client/Server 配置 |
| `dt upgrade` | `uv tool upgrade dual-tmux` |

## 卸载

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```
