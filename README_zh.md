# dual-tmux

[English](README.md)

双层 tmux 隧道。物理会话仍是普通 tmux；本 CLI 给它们命名，并按 1:1 绑定。

```
源主机（你的笔记本）
  op_<name>          trigger opencode
       │  dt-<name>
  run_<name>         ssh / docker exec → /workspace
                          └─ bullet opencode
```

目标主机的 SSH 必须已经能通。dual-tmux 不保存任何密钥。

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
dt config --init tm_andy_ouc   # 来源名必须以 tm_ 开头
dt doctor                      # 检查 tmux、ssh tom7r、persist cron
```

`run_*` 是**本机跳板会话**。pane 里执行 ssh（可选再 `docker exec`）进入工作目录。默认不要在远端再套一层 tmux。

## 用法

```sh
dt --version
dt doctor

dt new cp-gateway --host tom7r --container tmux_general_sessions --dir /workspace/cp-gateway
dt ls
dt show dt-cp-gateway

dt enter dt-cp-gateway     # 接入 op_*
dt work  dt-cp-gateway     # 接入 run_*
dt re    dt-cp-gateway     # 跳板掉回本机 shell 时，重新打入 ssh/docker

dt bind dt-cp-gateway --trigger stellar-island --bullet mighty-circuit
dt send dt-cp-gateway '发给 bullet agent 的任务'

dt                         # 接入最近一条隧道的 op_*
```

`dt new NAME` 会展开成 `dt-NAME` / `op_NAME` / `run_NAME`。一条隧道只绑一对 op 和 run。

登记文件跟着 tmux persist 同步到枢纽：

```
~/sessions/tmux/<tm_来源>/dt/dt-<name>.json
~/sessions/tmux/<tm_来源>/entry/run_<name>.cmd
```

## 命令

| 命令 | 作用 |
|------|------|
| `dt` / `dt enter` | 接入线头会话 op_* |
| `dt work` | 接入工作区跳板 run_* |
| `dt re` | 重新打入跳板命令 |
| `dt new` | 创建会话并登记 |
| `dt ls` / `dt show` | 查看 |
| `dt bind` | 绑定 trigger/bullet 的 opencode slug |
| `dt send` | 向 `run_*` 发送 `tmux send-keys` |
| `dt doctor` | 检查本机环境 |
| `dt config --init` | 写入 `tm_` 来源名 |
| `dt upgrade` | `uv tool upgrade dual-tmux` |

## 卸载

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```
