# Pane parsers

Web I/O is a snapshot of tmux. Each **tool version** has a named parser method.
Trigger and bullet pick independently.

## Id

`{tool}@{major.minor}` e.g. `opencode@1.18`.

Aliases: `opencode` → current default (`opencode@1.18`). Unknown `opencode@9.9`
falls back to the same tool's default, not to a different tool.

Register a new method when the TUI chrome changes; keep the old id so frozen
tunnels still parse.

## Bind

On freeze, `trigger.parser` / `bullet.parser` are filled from `tool` if empty.

Override:

```sh
# in tunnel JSON, or later a dt bind flag
"trigger": { "tool": "opencode", "parser": "opencode@1.18" }
"bullet":  { "tool": "opencode", "parser": "opencode@1.19" }
```

## Output

`ParsedTurn`: `body`, `model`, `elapsed`, plus `tool` / `parser`.
Other tools start as `plain` (last N lines, no chrome strip).
