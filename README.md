# dual-tmux

[中文文档](README_zh.md)

Dual tmux tunnels. Physical sessions stay ordinary tmux; this CLI names them and binds them 1:1.

```
Client (this machine)
  op_<name>          trigger agent
       │  dt-<name>
  run_<name>         ssh / docker exec → Server workspace
                          └─ bullet agent
```

**Client** is the laptop you sit at. **Server** is the ssh host where work happens (optional container). SSH to Server must already work. dual-tmux never stores keys.

Machine-local data lives in `~/.dual-tmux/` (`DUAL_TMUX_HOME` overrides).

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash
```

Or with uv:

```sh
uv tool install git+https://github.com/yukai08008/dual-tmux.git
```

## Setup

```sh
dt config --init --client laptop --server myserver
dt doctor
```

`~/.dual-tmux/config.toml`:

```toml
client = "laptop"      # this machine
server = "myserver"    # ssh Host alias in ~/.ssh/config
workspace = "/workspace"
```

`run_*` is a **local jump session**. The pane SSHes (and optionally `docker exec`) into the Server workspace. Do not nest another tmux on the Server by default.

## Usage

```sh
dt --version
dt doctor

dt new myapp --container appbox --dir /workspace/myapp
dt ls
dt show dt-myapp

dt enter dt-myapp     # attach op_*
dt work  dt-myapp     # attach run_*
dt re    dt-myapp     # re-send ssh/docker if the jump dropped to local shell

dt bind dt-myapp --trigger trigger-slug --bullet bullet-slug
dt send dt-myapp 'task for the bullet agent'

dt                    # attach latest op_*
```

`dt new NAME` expands to `dt-NAME` / `op_NAME` / `run_NAME`. One tunnel binds exactly one op and one run.

```
~/.dual-tmux/
├── config.toml
├── tunnels/dt-<name>.json
└── entries/run_<name>.cmd
```

## Commands

| Command | What |
|---------|------|
| `dt` / `dt enter` | attach the line-head session |
| `dt work` | attach the workspace jump |
| `dt re` | reconnect the jump command |
| `dt new` | create sessions + registry |
| `dt ls` / `dt show` | inspect |
| `dt bind` | bind trigger/bullet session slugs |
| `dt send` | `tmux send-keys` into `run_*` |
| `dt doctor` | check local setup |
| `dt config --init` | write Client/Server config |
| `dt upgrade` | `uv tool upgrade dual-tmux` |

## Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```
