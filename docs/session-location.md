# Session location & consistency model

One sentence: **a bullet is pinned to its environment (data stays, people move);
a trigger follows the operator (snapshot moves with people).**

Invariant: one tunnel/session is active at a time, it can be operated from any
Client, and every Client operates on the latest data.

## Bullet — pinned to the work point

A remote bullet OpenCode runs **at the jump target** (server / container), and
its session lives in that environment's sqlite (`opencode.db`). It is never
copied anywhere:

- Any Client operating the bullet re-enters the same `runtime.cmd` hops and
  resumes the same `session_id` against the same sqlite.
- Consistency comes from a **single source of truth**, not from syncing.
- `dt resume` fences the session before re-attaching: if the pane already shows
  the live agent TUI it does nothing; otherwise orphaned processes holding the
  same session on the server are terminated first (TERM, then KILL). One
  session, one writer.
- Hub mode additionally enforces a single active Client via the per-tunnel
  lock (`holder` + idle check).

A **local-mode** bullet (runtime has no server) lives in the Client sqlite and
follows the trigger rules below.

## Trigger — follows the operator

The trigger OpenCode runs on the Client you are physically using, and its
session lives in that Client's local sqlite. Switching machines moves the
trigger, via the persist tree:

```
old Client:  dt tick exports changed sessions  →  ~/sessions/opencode/<tenant>/
             persist cron rsyncs               →  hub ~/<user>/sessions/opencode/<tenant>/
new Client:  persist pull + dt pull            →  local snapshot + tunnel binding
             dt resume                         →  import JSON, then `opencode --auto -s <id>`
```

Properties of the export (implemented in `oc.export_snapshot`, driven by
`dt tick` and therefore cron every minute):

- Only the Client holding the tunnel lock exports (single writer).
- Freshness-gated on the session's `time_updated` — unchanged sessions are
  not re-exported.
- Atomic write-then-rename; the exported JSON's `info.id` is verified against
  the bound session before replacing the previous snapshot.
- Written into the tenant directory the persist cron actually syncs
  (`~/.config/session-persist/name`, falling back to the dt `client` id).
- Resume picks the newest snapshot across all `tm_*` sources by mtime.
- Failures are logged as `persist.export.fail` events and never break a tick.

## The Hub carries bindings and snapshots, not bullet data

| Data | Lives | Synced? |
|------|-------|---------|
| Tunnel bindings (`tunnels/`), jump entries (`entries/`) | every Client + Hub | merge-sync each `dt tick` |
| Trigger conversation JSON | owning Client sqlite + persist tree | export → Hub → import on resume |
| Remote bullet conversation | work-point sqlite only | **no** — attach the same session |
| Local-mode bullet conversation | Client sqlite | same as trigger |

## Failure visibility

- Each `op_*`/`run_*` tmux status bar shows the sync chip: yellow spinner
  `同步中` while a persist rsync holds its lock, green `已同步 HH:MM` after a
  successful Hub sync, red `同步失败` on error; refreshed by the minute tick
  and the daemon.
- The last Hub sync result is recorded in `~/.dual-tmux/hub-sync.json`.
- Unhandled CLI crashes are logged as `cmd.fail` events (`dt log`), so
  cron-side failures are visible instead of being swallowed by `>/dev/null`.
