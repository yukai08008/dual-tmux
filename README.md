# dual-tmux

Dual tmux tunnels. Physical sessions stay ordinary tmux; this CLI names them and binds them 1:1.

```
source host (your laptop)
  op_<name>          trigger opencode
       │  dt-<name>
  run_<name>         ssh / docker exec → /workspace
                          └─ bullet opencode
```

SSH to the target host must already work. dual-tmux never stores keys.

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
dt config --init tm_andy_ouc   # source name must start with tm_
dt doctor                      # tmux, ssh tom7r, persist cron
```

`run_*` is a **local jump session**. The pane command SSHes (and optionally `docker exec`) into the workspace. Do not nest another tmux on the remote by default.

## Usage

```sh
dt --version
dt doctor

dt new cp-gateway --host tom7r --container tmux_general_sessions --dir /workspace/cp-gateway
dt ls
dt show dt-cp-gateway

dt enter dt-cp-gateway     # attach op_*
dt work  dt-cp-gateway     # attach run_*
dt re    dt-cp-gateway     # re-send ssh/docker if the jump dropped to local shell

dt bind dt-cp-gateway --trigger stellar-island --bullet mighty-circuit
dt send dt-cp-gateway 'task for the bullet agent'

dt                         # attach latest op_*
```

`dt new NAME` expands to `dt-NAME` / `op_NAME` / `run_NAME`. One tunnel binds exactly one op and one run.

Registry files live with tmux persist and sync to the hub:

```
~/sessions/tmux/<tm_source>/dt/dt-<name>.json
~/sessions/tmux/<tm_source>/entry/run_<name>.cmd
```

## Commands

| Command | What |
|---------|------|
| `dt` / `dt enter` | attach the line-head session |
| `dt work` | attach the workspace jump |
| `dt re` | reconnect the jump command |
| `dt new` | create sessions + registry |
| `dt ls` / `dt show` | inspect |
| `dt bind` | bind trigger/bullet opencode slugs |
| `dt send` | `tmux send-keys` into `run_*` |
| `dt doctor` | check local setup |
| `dt config --init` | write `tm_` source name |
| `dt upgrade` | `uv tool upgrade dual-tmux` |

## Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```
