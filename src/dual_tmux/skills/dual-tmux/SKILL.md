---
name: dual-tmux
description: Dual tmux tunnels. You are the trigger OpenCode in op_*. Bullet lives in run_*. Use dt inspect / dt work / tmux send-keys. Never ssh the task yourself.
trigger: When this session is a DT trigger, or the user mentions dt-, op_*, run_*, DST, trigger/bullet.
---

# dual-tmux (trigger)

This launch directory is `~/.dual-tmux/ops/<op_*>/`. You are the **trigger**.

- DT = local tmux pair `op_*` (this pane) + `run_*` (jump to Server).
- DST = that pair plus frozen OpenCode session ids on both sides.
- Work is dispatched with `tmux send-keys -t <run_*>`, then you detach and poll. See `tmux-trigger`.

```sh
dt inspect                 # this tunnel
dt work                    # attach run_* (do not stay there to run the task)
dt re                      # re-send ssh/docker into run_*
tmux send-keys -t <run_*> -- 'task...' Enter
```

Resume uses `opencode --auto -s <id>`, never `-c`.

If bullet asks to rebuild / replace its workspace container: **you** do that on the host (outside the container), then `dt re`. Bullet must not docker-rebuild the box it is sitting in.

Architecture and flow questions: send to bullet; require mermaid diagrams **filed in the workspace**, not only in chat. See `tmux-trigger`.

Bindings live in `dt inspect`. Another Client: `dt pull` then `dt resume` (imports trigger persist JSON locally; bullet `-s` at the jump sqlite). Hub lock: only one Client active; `dt drop` kills local tmux and releases. `dt push` does not copy `config.toml`. Container names are not persist sources.
