# Persist sync (tenant layer)

This is the contract between dual-tmux and the optional persist tools.
`dt` never writes these trees. Resume still depends on them for **trigger**.

## Three trees

| Tree | Client | Server (hub) | Owns |
|------|--------|--------------|------|
| tmux persist | `~/sessions/tmux/<tm_*>/` | `~/<user>/sessions/tmux/<tm_*>/` | windows / pane snapshot |
| OpenCode persist | `~/sessions/opencode/<tm_*>/` | `~/<user>/sessions/opencode/<tm_*>/` | conversation JSON |
| dt hub | `~/.dual-tmux/{tunnels,entries}` | `~/<user>/dual-tmux/` | DT/DST binding only |

`user` is the person (`andy`), not a hostname and not `tm_*`.
Several people on one Server: each has `~/<user>/sessions` and `~/<user>/dual-tmux`.

Do **not** rsync `~/sessions/{tmux,opencode}` onto the Server login home.
That path has no tenant and collides with other people.

## `tm_` is a machine source, not a hop

`~/.config/session-persist/name` (same value as `dt` `client`) names the **writer machine**.

Legal: `tm_` + `[A-Za-z0-9._-]`. Example: `tm_andy_home`, `tm_m7`.

It is **not**:

- a tmux session name (`op_msg`, `run_msg`)
- a docker container name
- a workspace directory
- whatever pane you `ssh` / `docker exec` into

`run_*` jumping into a container does not create a persist source and does not rename one.
Illegal source dirs (`andy_messenger/`, hostname leftovers) are pruned and never pulled.

## Who restores what on `dt resume`

```
Client B
  dt pull                         # tunnels only (session_id / slug / jump cmd)
  persist pull                    # JSON into ~/sessions/opencode/tm_*/
  dt resume
       ├─ trigger (op_*): local sqlite must contain session_id
       │     import JSON first, then `opencode --auto -s <id>`
       └─ bullet  (run_*): replay jump, then `-s` in that pane
             uses the sqlite at the work point (Server / container)
             Client B does not import bullet JSON
```

Trigger OpenCode lives on the Client. Another laptop has an empty sqlite → Session not found unless persist JSON is imported.

Bullet OpenCode lives at the jump target. Resume re-enters the same `runtime.cmd` / hops and talks to that sqlite. Container name is irrelevant.

## Persist cron (not this CLI)

Client, every minute:

1. export this machine's OpenCode sessions into `~/sessions/opencode/<client>/`
2. rsync that directory to `server:<user>/sessions/opencode/<client>/`
3. pull other `tm_*` sources from the same tenant path
4. same pattern for tmux resurrect under `.../sessions/tmux/`

Hub host only saves its own `tm_*` into `~/<user>/sessions/...`. It does not push (NAT Clients pull).

`dt push` / `dt pull` never copy persist JSON.

## Other Client checklist

```sh
dt config --init --client tm_<this-box> --server <ssh-host> --user <person>
# persist identity (same person, this box's tm_ name)
echo tm_<this-box> > ~/.config/session-persist/name
echo <person>      > ~/.config/session-persist/user
dt pull
# persist cron must have pulled trigger JSON into ~/sessions/opencode/tm_*/
dt resume dt-msg
```

If trigger `-s` says Session not found, the binding arrived and the JSON did not.
Fix persist rsync to `~/<user>/sessions/opencode/`, then import, then resume.
Do not look at docker names.
