# dual-tmux

[中文文档](README_zh.md) · [Persist sync](docs/persist-sync.md) · [Memory](docs/memory.md)

Dual tmux tunnels. Physical sessions stay ordinary tmux; this CLI names them and binds them 1:1. dual-tmux has two foundational operating modes: **local-only** and **Hub sync**.

```
Client (this machine)
  op_<name>          trigger agent  (OpenCode by default)
       │  dt-<name>
  run_<name>         local workspace, or ssh / docker exec → Server workspace
                          └─ bullet agent  (OpenCode by default)
```

**Client** is the machine you sit at. **Server / Hub** is optional: when configured, it is both the default SSH work target for new tunnels and the synchronization center for tunnel records. dual-tmux never stores keys.

## Foundational operating modes

This is a persistent project model, not only a first-install choice. Every Client is always in exactly one of these modes:

| Mode | Required config | New tunnel runtime | Tunnel records | Network and locking |
|---|---|---|---|---|
| **Local-only** | `client` | Local workspace; current directory by default | Only `~/.dual-tmux/` on this Client | No SSH, rsync, Hub push/pull, or distributed lock |
| **Hub sync** | `client` + `server` + `user` | `server`, `/workspace` by default; per-tunnel overrides still work | Local copy plus `~/<user>/dual-tmux/` on the Hub | Automatic merge-sync and one-Client-at-a-time Hub lock |

Local-only mode is fully functional: it can create, enter, work, freeze, resume, and manage local tunnels without a server. Hub mode adds cross-Client discovery, synchronization, takeover protection, and remote persist integration; it is not required for basic operation.

Mode changes are supported at any time:

```sh
# Start local-only
dt config --init --local --client tm_laptop

# Attach the first Hub, or replace the current Hub
dt config --server tom7r --user andy

# Merge once more, then return to local-only
dt config --local
```

The transition is merge-before-commit: dual-tmux merges the old Hub first when one exists, merges the candidate Hub when attaching or replacing, and atomically writes `config.toml` only after all required syncs succeed. A failed SSH/rsync leaves the previous mode and config unchanged. Switching mode does not rewrite existing tunnels' `runtime`; it only changes synchronization behavior and the defaults for tunnels created later. Deletions are never propagated during a merge.

## First start

Install puts `dt` on PATH **and** a minute crontab (`dt tick`). Choose either foundational mode. Local tunnels default to the current directory; Hub-mode jumps default to `/workspace` until `dt new --dir` overrides them.

| Field | What you type | What this CLI does **not** do |
|-------|----------------|-------------------------------|
| `client` | Legal **local source name**: `tm_` + `[A-Za-z0-9._-]`. Example: `tm_laptop`. Not a hostname. | Does not invent a name from `hostname`. |
| `server` | Optional synchronization Hub and default jump target. Whatever `ssh` can reach. | Does not write `~/.ssh/config`, keys, or `known_hosts`. |
| `user` | Required with `server`. Person id: `[A-Za-z][A-Za-z0-9._-]`. Example: `ouc`. | Does not create OS accounts. |

```sh
dt config --init --local --client tm_laptop  # no server dependency

# Or configure the Hub immediately (the existing command stays compatible)
dt config --init --client tm_laptop --server myserver --user ouc
ssh myserver          # must already work
dt doctor
```

Local-only `~/.dual-tmux/config.toml`:

```toml
client = "tm_laptop"
workspace = "/path/to/my-project"
```

Hub-mode `~/.dual-tmux/config.toml`:

```toml
client = "tm_laptop"   # this machine's source name
server = "myserver"    # ssh Host alias in ~/.ssh/config
user = "ouc"           # person; remote persist ~/<user>/sessions
workspace = "/workspace"  # default jump dir; not asked at init
```

If config is missing, `dt` prompts for local or Hub mode (TTY only). Local mode checks the Client runtime only; Hub mode also checks `ssh <server>`. SSH stays yours.

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

## Another Client in Hub mode (continue a DST)

This is a **third tree**. It does not collide with tmux persist or OpenCode persist.

| Tree | Path | What |
|------|------|------|
| tmux persist | `~/sessions/tmux/tm_*/` | windows / processes / screen |
| OpenCode persist | `~/sessions/opencode/tm_*/` | conversation JSON |
| **dt hub** | Server `~/<user>/dual-tmux/` | DT/DST bindings only |

Hub sync is **automatic**: `new` / `freeze` / `bind` / `enter` / `work` / `resume` push in the background; the minute `dt tick` merges local and Hub `tunnels/` + `entries/` by `updated_at`, so tunnels created on another Client appear automatically. Use `dt push` / `dt pull` for an immediate one-way sync. Local-only mode performs no network sync or distributed locking. Never copies `config.toml`, `ops/`, or `events.jsonl`.

```sh
# other machine — tick discovers it automatically; pull to continue now
dt pull && dt resume dt-msg
```

On the other machine:

```sh
uv tool install git+https://github.com/yukai08008/dual-tmux.git
dt config --init --client tm_<that-box> --server tom7r --user andy
ssh tom7r    # must already work; dt does not write ~/.ssh
dt pull
dt resume dt-msg              # imports trigger JSON, then -s; bullet -s on the jump host
```

`dt pull` restores the binding only. `dt resume` imports **trigger** JSON from persist into this Client sqlite, then `opencode --auto -s <id>` in `op_*`. Bullet stays at the jump target sqlite — replay `runtime.cmd`, then `-s` there. Do not import bullet JSON onto the laptop. See [docs/persist-sync.md](docs/persist-sync.md).

One Client at a time: hub lock `~/<user>/dual-tmux/locks/<dt-name>` (`client@epoch`, TTL 300s). `enter` / `work` / `resume` claim it.

Idle is **not** the lock TTL. `dt tick` hashes pane tails every minute. Another Client `dt resume` takes over if the last **30 ticks** are frozen. The old Client's local `op_*`/`run_*` are **killed** (not renamed `__parked`). Binding stays on the hub; oc JSON stays in persist. Next `dt resume` recreates the light tmux pair. Leave now: `dt drop dt-msg`. Steal: `--force`.

To **branch** (two live tunnels, not steal the lock):

```sh
dt branch dt-msg dt-msg-v2
```

This **replays** the recorded jump (`runtime.cmd` or hops: ssh → docker → cwd), starts **new** OpenCode on both sides (same models, **new** `session_id`), and freezes the branch as its own DST. Source `dt-msg` stays locked and running. Same container is fine; do not reuse the parent oc sessions.

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

Each frozen side stores `tool`, `model`, `session_id`, and `agent_client` (client name, version, raw version output, executable, local/ssh/docker location, and collection time). OpenCode, Codex, and Claude Code are recognized. OpenCode keeps session resume support; Codex/Claude currently record client metadata only and never fabricate a resumable session. If a remote pane only exposes `ssh`, select it explicitly with `dt freeze --tool codex|claude`. OpenCode resume uses `opencode --auto -s <id>`, never `-c`.

Freeze also records **work points** (`op_point` / `run_point`: kind, cwd, ssh, docker, resume_cmd) and **timestamps** (`created_at`, `enter_at`, `work_at`, `freeze_at`, `resume_at`). One side failing does not throw away the other. `dt inspect` shows all of this.

`run_*` is a **local jump session**. The pane SSHes (and optionally `docker exec`) into the Server workspace. Do not nest another tmux on the Server by default.

## Commands

| Command | What |
|---------|------|
| `dt new <name>` | create **DT** only (`op_*` + `run_*`) |
| `dt branch <src> <dest>` | replay jump, start **new** oc both sides, freeze DST |
| `dt rm <name> [-y] [--kill]` | unregister DT; `--kill` also destroys op_*/run_* tmux |
| `dt enter <name>` | attach op tmux |
| `dt work <name>` | attach run tmux |
| `dt enter --oc [--model M]` | start trigger oc in op |
| `dt work --oc [--model M]` | start bullet oc in run |
| `dt freeze <name>` | freeze both oc; **DST** only if both exist |
| `dt model <name> [--run|--op] <id>` | quit that oc, restart with new model, freeze |
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
| `dt doctor` | check Client tmux + optional Hub; reconcile persist sync |
| `dt config --init [--local]` | initialize local-only or Hub mode |
| `dt config --server H --user U` | safely attach or replace the Hub |
| `dt config --local` | safely detach the Hub after a final merge |
| `dt upgrade` | `uv tool upgrade dual-tmux`, then persist tenant hotfix |
| `dt mem [name] [set k v]` | shared or per-agent MEMORY.json facts |
| `dt note <name> '…'` | append sqlite note for that agent |
| `dt notes <name> [--day] [--q]` | list / FTS-search agent notes |
| `dt web [--port 8787] [--no-open]` | local admin UI; opens the default browser unless disabled |
| `dt skill ls\|import\|enable\|teach\|used\|log` | catalog in ~/.dual-tmux/skills; trigger subset; teach bullet; usage log |

## Uninstall

```sh
curl -fsSL https://raw.githubusercontent.com/yukai08008/dual-tmux/main/install.sh | bash -s -- uninstall
```

Uninstall removes the `dt` binary. `~/.dual-tmux/` is kept. tmux sessions, OpenCode DB, and `~/sessions/` are untouched.
