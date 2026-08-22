# Memory

Two stores. Neither is OpenCode sqlite and neither is persist JSON.

| Store | Path | Shape | Command |
|-------|------|-------|---------|
| shared facts | `~/.dual-tmux/MEMORY.json` | `{facts, updated_at}` | `dt mem` / `dt mem set k v` |
| agent facts | `~/.dual-tmux/ops/<op_*>/MEMORY.json` | same | `dt mem <dt>` / `dt mem <dt> set k v` |
| agent log | `~/.dual-tmux/ops/<op_*>/memory.sqlite` | notes + FTS5 | `dt note` / `dt notes` |

`dt new` / `dt enter --oc` / `dt resume` call `prepare` and create empty files.

## JSON facts

Stable, small, structured. Keys you intend to reuse (container id, workspace path, person).

```sh
dt mem                         # dump shared
dt mem set server tom7r
dt mem dt-msg2                 # dump this tunnel's agent facts
dt mem dt-msg2 set container andy_messenger_…
```

## sqlite notes

Append-only log for what happened. Filter by calendar day and full-text search.

```sh
dt note dt-msg2 'froze trigger nimble-wizard'
dt note dt-msg2 --title rebuild --kind decision 'host must recreate container'
dt notes dt-msg2
dt notes dt-msg2 --day 2026-08-21
dt notes dt-msg2 --since 2026-08-01 --until 2026-08-31
dt notes dt-msg2 --q 'container OR mermaid'
```

FTS uses SQLite FTS5 (`MATCH`). `--day` is `YYYY-MM-DD` local to the Client that wrote the row.

Trigger reads these paths from `AGENTS.md`. Do not rsync `memory.sqlite` with the OpenCode live DB.
