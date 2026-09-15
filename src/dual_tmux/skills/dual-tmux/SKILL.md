---
name: dual-tmux
description: Dual tmux tunnels. You are the trigger OpenCode in op_*. Bullet lives in run_*. Use dt inspect / dt work / dt send / dt bullet / dt rebuild. Never ssh the task yourself.
trigger: When this session is a DT trigger, or the user mentions dt-, op_*, run_*, DST, trigger/bullet.
---

# dual-tmux (trigger)

This launch directory is `~/.dual-tmux/ops/<op_*>/`. You are the **trigger**.

- DT = local tmux pair `op_*` (this pane) + `run_*` (jump to Server).
- DST = that pair plus frozen OpenCode session ids on both sides.
- Work is dispatched with `dt send <dt> 'task...'` (occupancy-guarded, recorded as a bullet.send event), then you detach and poll on token/tool/body evidence, not spinner; 8 quiet rounds then `dt rebuild` before reporting. Development models on bullet: `gpt-5.6-sol` → `grok-4.6` → `gpt-5.6-terra` or `gpt-5.5`. Switch with `dt model --run`. See `tmux-trigger`.

```sh
dt inspect                 # this tunnel
dt bullet --json           # bullet state/health/transport/writers/events + hint
dt work                    # attach run_* (do not stay there to run the task)
dt send <dt> 'task...'     # dispatch to bullet (guarded + evented)
dt rebuild <dt>            # fenced recovery: route + jump + fence + restart
dt log --name <dt> --cat bullet -n 10   # recent bullet events
```

Resume/recovery goes through `dt rebuild` (bound session, fenced start), never hand-typed `opencode --auto -s`, and never `-c`.

If bullet asks to rebuild / replace its workspace container: **you** do that on the host (outside the container), then `dt rebuild`. Bullet must not docker-rebuild the box it is sitting in.

Architecture and flow questions: send to bullet; require mermaid diagrams **filed in the workspace**, not only in chat. See `tmux-trigger`.

Structured facts: shared `~/.dual-tmux/MEMORY.json` (`dt mem`) and this agent `ops/<op_*>/MEMORY.json` (`dt mem <dt>`). Day-scoped / FTS notes: `dt note` / `dt notes` against `memory.sqlite`.

Bindings live in `dt inspect`. Another Client: `dt pull` then `dt resume` (imports trigger persist JSON locally; bullet `-s` at the jump sqlite). Hub lock: only one Client active; `dt drop` kills local tmux and releases. `dt push` does not copy `config.toml`. Container names are not persist sources.
