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

Install puts `dt` on PATH **and** a minute crontab (`dt tick`). The first real command asks for **three fields**. Jump directory is always `/workspace` until you override a tunnel with `dt new --dir`.

| Field | What you type | What this CLI does **not** do |
|-------|----------------|-------------------------------|
| `client` | Legal **local source name**: `tm_` + `[A-Za-z0-9._-]`. Example: `tm_laptop`. Not a hostname. | Does not invent a name from `hostname`. |
| `server` | Whatever `ssh` can reach. Paste `ssh -p 22 root@IP`: if `~/.ssh/config` has a matching Host, that alias is stored; otherwise `root@IP`. Pretty names are optional. | Does not write `~/.ssh/config`, keys, or `known_hosts`. Does not use the remote hostname. |
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
├── entries/run_<name>.cmd    # reconnect command for run_*
├── events.jsonl              # CLI event / operation log
├── skills/                   # trigger skills copied from the installed package
└── ops/op_<name>/AGENTS.md   # launch dir for trigger OpenCode
```

## Another Client (continue a DST)

This is a **third tree**. It does not collide with tmux persist or OpenCode persist.

| Tree | Path | What |
|------|------|------|
| tmux persist | `~/sessions/tmux/tm_*/` | windows / processes / screen |
| OpenCode persist | `~/sessions/opencode/tm_*/` | conversation JSON |
| **dt hub** | Server `~/<user>/dual-tmux/` | DT/DST bindings only |

Hub push is **automatic**: `new` / `freeze` / `bind` / `enter` / `work` / `resume` rsync `tunnels/` + `entries/` in the background. `dt push` is only if you want it now (blocks until rsync finishes). Never copies `config.toml`, `ops/`, or `events.jsonl`.

```sh
# other machine — no extra dt push on this laptop
dt pull && dt resume dt-msg
```

On the other machine:

```sh
uv tool install git+https://github.com/yukai08008/dual-tmux.git
dt config --init --client tm_<that-box> --server tom7r --user andy
ssh tom7r    # must already work; dt does not write ~/.ssh
dt pull
# if the oc sqlite on that box is empty, oc-restore the trigger/bullet JSON
# from persist (~/sessions/opencode/tm_*/<slug>.json) first
dt resume dt-msg
```

`dt pull` restores the binding. `dt resume` starts `opencode --auto -s <id>` in `op_*` / `run_*`. Without persist restore, `-s` will say session not found. Each Client keeps its own `tm_*` in `config.toml`.

One Client at a time: hub lock `~/<user>/dual-tmux/locks/<dt-name>` (`client@epoch`, TTL 300s). `enter` / `work` / `resume` claim it.

Idle is **not** the lock TTL. `dt tick` hashes pane tails every minute. Another Client `dt resume` takes over if the last **30 ticks** are frozen. The old Client's local `op_*`/`run_*` are **killed** (not renamed `__parked`). Binding stays on the hub; oc JSON stays in persist. Next `dt resume` recreates the light tmux pair. Leave now: `dt drop dt-msg`. Steal: `--force`.

Install / `dt doctor` writes that crontab. Other machine: same one-liner install, then `dt pull && dt resume`. No extra cron step.

Trigger OpenCode starts in `ops/op_*` so it always reads `AGENTS.md`, which points at packaged `dual-tmux` + `tmux-trigger` skills. Same layout after `uv tool install` on any machine.

Treat `dt` like a small server: every command appends JSON lines to `events.jsonl` (`cmd.start` / `cmd.ok` / `cmd.fail`, plus `freeze.start` / `freeze.side.ok` / `freeze.side.fail` / `freeze.ok`). `dt log` is the audit view. Freeze failures are events, not only a one-line stderr.

If you also persist tmux / OpenCode (optional, separate tools), those trees are **not** dual-tmux:

| Who | Path | Rule |
|-----|------|------|
| this CLI | `~/.dual-tmux/` | tunnels + jump cmds |
| dt hub (Server) | `~/<user>/dual-tmux/{tunnels,entries}` | `dt push` / `dt pull`; not persist |
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

## Command flow

```
DT  = op tmux + run tmux
DST = DT + op-oc + run-oc   (both oc sessions frozen)
```

```
dt new myapp
        │
        ├─ dt enter myapp              op tmux
        │       └─ --oc [--model M]    start trigger OpenCode
        │
        ├─ dt work myapp               run tmux
        │       └─ --oc [--model M]    start bullet OpenCode
        │
        ├─ dt freeze myapp             record both oc (tool/model/session_id)
        │                              IS_DST=yes only if both sides have oc
        │
        ├─ dt ls                       col1=DT  col2=IS_DST
        │
        ├─ dt make dst myapp [--tool opencode] [--model M]
        │                              one-shot: new + both oc + freeze
        │
        └─ dt resume myapp             reconnect dropped op-oc / run-oc, then attach
```

Step by step:

```sh
dt doctor

dt new myapp                          # DT only
dt enter myapp                        # attach op_*
dt work  myapp                        # attach run_*
dt enter myapp --oc --model glm-5.1   # start oc in op
dt work  myapp --oc --model glm-5.1   # start oc in run
dt freeze myapp                       # freeze both; DST iff both exist
dt ls                                 # DT | IS_DST | OP | RUN | TRIGGER | BULLET

dt make dst myapp --model glm-5.1     # same result in one command
dt resume myapp                       # oc dropped out → auto --auto -s <id>
dt send myapp 'task for bullet'
```

`dt new` never creates DST. `--oc` may omit `--model` (harness default). `dt freeze` is required after manual `--oc`. `dt resume` is the DST continue command (not a typo for `dsh`).

Each frozen side stores `tool` (default `opencode`), `model`, `session_id`. Resume uses `opencode --auto -s <id>`, never `-c`.

Freeze also records **work points** (`op_point` / `run_point`: kind, cwd, ssh, docker, resume_cmd) and **timestamps** (`created_at`, `enter_at`, `work_at`, `freeze_at`, `resume_at`). One side failing does not throw away the other. `dt inspect` shows all of this.

`run_*` is a **local jump session**. The pane SSHes (and optionally `docker exec`) into the Server workspace. Do not nest another tmux on the Server by default.

## Commands

| Command | What |
|---------|------|
| `dt new <name>` | create **DT** only (`op_*` + `run_*`) |
| `dt rm <name> [-y] [--kill]` | unregister DT; `--kill` also destroys op_*/run_* tmux |
| `dt enter <name>` | attach op tmux |
| `dt work <name>` | attach run tmux |
| `dt enter --oc [--model M]` | start trigger oc in op |
| `dt work --oc [--model M]` | start bullet oc in run |
| `dt freeze <name>` | freeze both oc; **DST** only if both exist |
| `dt ls` | col1 DT, col2 IS_DST |
| `dt make dst <name> [--tool] [--model]` | one-shot DT + both oc + freeze |
| `dt resume <name> [--force]` | resume DST; `--force` steals hub lock |
| `dt drop <name>` | kill local op_*/run_* and release lock; hub binding kept |
| `dt tick` | minute job (install/doctor adds crontab) |
| `dt cron [--remove]` | install or remove the tick crontab |
| `dt push` | rsync now (otherwise freeze/new/work already push in the background) |
| `dt pull` | rsync tunnels+entries ← hub; does not overwrite `client` |
| `dt re <name>` | re-send ssh/docker into run_* |
| `dt send <name> '…'` | `tmux send-keys` into run_* (bullet) |
| `dt inspect <name>` | DT + op/run tool, model, session_id (empty allowed) |
| `dt log [-n] [--kind freeze] [--name dt-msg]` | CLI event log |
| `dt show <name>` | raw tunnel JSON |
| `dt` | attach latest op_* |
| `dt doctor` | check Client tmux + ssh (does not change SSH) |
| `dt config --init` | write client + server + user |
| `dt upgrade` | `uv tool upgrade dual-tmux` |

## Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```

Uninstall removes the `dt` binary. `~/.dual-tmux/` is kept. tmux sessions, OpenCode DB, and `~/sessions/` are untouched.
