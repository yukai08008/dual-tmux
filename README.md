# dual-tmux

[中文文档](README_zh.md)

Dual tmux tunnels. Physical sessions stay ordinary tmux; this CLI names them and binds them 1:1.

```
Client (this machine)
  op_<name>          trigger agent  (OpenCode by default)
       │  dt-<name>
  run_<name>         ssh / docker exec → Server workspace
                          └─ bullet agent  (OpenCode by default)
```

**Client** is the laptop you sit at. **Server** is the ssh host where work happens (optional container). dual-tmux never stores keys.

## First start

Install does nothing except put `dt` on PATH. The first real command (`dt`, `dt new`, `dt work`, or `dt config --init`) asks for **three fields**. Jump directory is always `/workspace` until you override a tunnel with `dt new --dir`.

| Field | What you type | What this CLI does **not** do |
|-------|----------------|-------------------------------|
| `client` | Legal **local source name**: `tm_` + `[A-Za-z0-9._-]`. Example: `tm_laptop`. Not a hostname. | Does not invent a name from `hostname`. |
| `server` | ssh **Host alias** that already works (`ssh myserver`). | Does not write `~/.ssh/config`, keys, or `known_hosts`. |
| `user` | Person id: `[A-Za-z][A-Za-z0-9._-]`. Example: `ouc`. Not `tm_*`. | Does not create OS accounts. |

```sh
dt config --init --client tm_laptop --server myserver --user ouc
ssh myserver          # must already work
dt doctor
```

`~/.dual-tmux/config.toml`:

```toml
client = "tm_laptop"   # this machine's source name
server = "myserver"    # ssh Host alias in ~/.ssh/config
user = "ouc"           # person; remote persist ~/<user>/sessions
workspace = "/workspace"  # default jump dir; not asked at init
```

If config is missing, `dt` prompts for those three fields (TTY only). Then it checks Client tmux + `ssh <server>`. SSH stays yours.

Also required: tmux on the Client. `op_*` / `run_*` are **local** sessions; `run_*` only uses ssh to reach the Server.

## Directories

This CLI only owns `~/.dual-tmux/` (`DUAL_TMUX_HOME` overrides). It does not write `~/sessions`.

```
~/.dual-tmux/                 # dual-tmux only
├── config.toml               # client + server + workspace
├── tunnels/dt-<name>.json    # 1:1 op/run binding
└── entries/run_<name>.cmd    # reconnect command for run_*
```

If you also persist tmux / OpenCode (optional, separate tools), those trees are **not** dual-tmux:

| Who | Path | Rule |
|-----|------|------|
| this CLI | `~/.dual-tmux/` | tunnels + jump cmds |
| tmux persist (Client) | `~/sessions/tmux/<tm_source>/` | source dir **must** be `tm_*` |
| tmux persist (Server) | `~/<user>/sessions/tmux/<tm_source>/` | same tree, namespaced by person |
| OpenCode persist (Client) | `~/sessions/opencode/<tm_source>/` | same `tm_*` source as tmux |
| OpenCode persist (Server) | `~/<user>/sessions/opencode/<tm_source>/` | same tree, namespaced by person |
| OpenCode live DB | `~/.local/share/opencode/opencode.db` | do not rsync the DB |
| OpenCode config | `~/.config/opencode/` | your model/auth, not this CLI |
| tmux live | tmux server memory + socket under `/tmp/tmux-*` | not files this CLI owns |
| ssh | `~/.ssh/` | yours; never touched |

`client` is the `tm_*` machine source. `user` is the person. Several laptops can share one Server if each `user` is unique: local stays `~/sessions`, remote is `~/<user>/sessions`.

## Default agent: OpenCode

The intended occupants of `op_*` (trigger) and `run_*` (bullet) are **[OpenCode](https://opencode.ai)** sessions.

That is a longevity choice: OpenCode is open source. Binding to a closed CLI (keys, proprietary session stores, surprise protocol changes) is how this kind of tunnel dies in a year. dual-tmux only names tmux sessions and `tmux send-keys`; the agent can be swapped, but the documented default is OpenCode so you hit fewer private-tool pits.

Install OpenCode yourself. This CLI does not vendor it.

## Assumptions

1. `ssh <server>` already works (Host alias + your keys).
2. tmux is installed on the Client.
3. A working directory exists on the Server (and in a container if you pass `--container`).
4. OpenCode is installed if you want the default trigger/bullet flow.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash
```

Or with uv:

```sh
uv tool install git+https://github.com/yukai08008/dual-tmux.git
```

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

`run_*` is a **local jump session**. The pane SSHes (and optionally `docker exec`) into the Server workspace. Do not nest another tmux on the Server by default.

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
| `dt doctor` | check Client tmux + ssh to Server (does not change SSH) |
| `dt config --init` | write `tm_*` client + ssh Host + user |
| `dt upgrade` | `uv tool upgrade dual-tmux` |

## Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```

Uninstall removes the `dt` binary. `~/.dual-tmux/` is kept. tmux sessions, OpenCode DB, and `~/sessions/` are untouched.
