---
name: tmux-trigger
description: Trigger agent dispatches work into the bullet OpenCode in run_* via tmux send-keys, then polls on real progress evidence with a quiet-round cap. Never wrap the task in ssh/docker exec -it.
trigger: When dispatching work, polling a bullet, resuming with --auto -s, or the user says 派活 / 放手 / trigger-bullet.
---

# tmux trigger

You are **trigger**. The task process must live in the **bullet** pane (`run_*`), not on your SSH.

```
派活 → 放手 → 轮询 → 再贴回去看
```

## Forbidden

```sh
ssh -t <server> 'docker exec -it <container> opencode run ...'
ssh -t <server> 'docker exec -it ... opencode --auto -s ses_xxx'
```

`docker exec -it` dies with SIGHUP when SSH drops.

## Dispatch

1. `tmux list-panes -t <run_*> -F 'cmd=#{pane_current_command}'`
2. If pane is shell: `dt re <dt>` then `opencode --auto -s <bullet-session-id>` inside that pane (via send-keys), wait for `Build auto`.
3. If pane is already `--auto` OpenCode: `tmux send-keys -t <run_*> -- 'task...' Enter`
4. Poll as below. Do not hold an SSH session as the task lifecycle.

Resume bullet with `opencode --auto -s <id>`, never `-c`. Before any new `--auto -s`, confirm the bound session has **zero** leftover opencode processes (or exactly one live TUI you will reuse). Escape / Ctrl+C does not count as dead.

## Poll

Sample every 15–30s with a fixed, bounded tail:

```sh
tmux capture-pane -t <run_*> -p -S -60 | tail -n 60 | head -c 12000
```

The poll window is a hard ceiling. Keep `-S -60`, `tail -n 60`, and the byte cap
fixed for every round. Never widen it to `-80`, `-200`, `-500`, etc. Never paste
the complete pane or previous poll results back into the trigger conversation.
Repeated full-pane captures recursively copy bullet history into trigger tool
results, producing duplicate-looking turns and exhausting trigger context.

At dispatch, record a baseline: context tokens / `% used`, last tool line, chrome-stripped body, and any expected output file. Each round compare to the last baseline.

**Progress evidence** (at least one must change):

- context tokens or `% used`
- a new tool call, or new output from a tool already in flight
- chrome-stripped assistant body
- an expected workspace file created or grown

Spinner, `esc interrupt`, elapsed time, progress bar, and footer animation are **not** progress. Flat tokens across rounds means the session is not growing.

**Quiet-round cap:** consecutive rounds with no evidence reset only when evidence moves. After **8** quiet rounds, stop waiting because it is spinning. Do not send more keys into a running or hung turn. Do not treat Escape as recovery. Run **Dead client** below. Pause and report only if that recovery fails.

If the bounded tail does not expose enough evidence, inspect a specific artifact
or run a targeted status command in bullet. Do not compensate by increasing the
pane history depth. Summarize each poll in trigger as changed evidence plus a
short hash/status; do not quote the captured tail unless the exact lines matter.

Idle/done: `Build auto` (or equivalent idle) **and** a new assistant result after this dispatch, not merely one frame without a spinner.

## Models (development)

Bullet does the coding. Before dispatching development work, put bullet on this ladder. Keep the provider already bound on that side (`dt inspect`).

1. `gpt-5.6-sol` — default
2. `grok-4.6` — if sol is missing, `dt model` probe fails, or a turn stalls with no progress evidence
3. `gpt-5.6-terra` or `gpt-5.5` — if both of the above fail; use whichever exists on the current provider

Switch with `dt model <dt> --run <provider>/<id>`. Do not type a model change into the TUI. Do not change provider unless the next id is not listed there. Do not switch during a healthy in-progress turn. If the user named a model, use that. Leave trigger's model alone unless the user asks.

## Dead client (stacked `--auto` + snapshot git)

Quiet rounds, a spinner, flat tokens, and no tools are **not** proof the model/gateway is dead. The common hang is OpenCode itself: several `--auto -s <same-id>` processes sharing one session, then blocking on internal snapshot git. Footer model can already be Grok while an old loop still streams a cooled Sol (`usage_limit_reached`). Not intro_v2 business code, not CLIProxy.

**Cause:** OpenCode does not mutex `--auto -s`, binds the chat loop to snapshot git (`gc` / `pack-objects` / `diff-files`), and Escape often only stops the turn. Repeated `dt re` / resume / `--auto -s` without killing leftovers, plus cooldown auto-retry, stacks the hole.

**Recover (do this before pausing the task):**

1. Count remote processes whose cmdline contains the bullet `session_id`. Must be 0 (then start one) or 1 (reuse that TUI). `dt resume` fences orphans only when the pane is **not** already a live TUI; if the TUI is attached and pids > 1, fence will skip — kill extras yourself.
2. If `opencode` has `git gc` / `pack-objects` / `repack` children, or logs loop `cleanup failed: gc is already running` / `failed to list snapshot files` under `~/.local/share/opencode/snapshot/`, the TUI will spin with unchanged tokens. Kill that opencode (TERM, then KILL) and leftover git. Do not `docker exec -it`.
3. Wait until that session has **zero** opencode pids. Then one `opencode --auto -s <id>` (after `dt re` if the pane is a shell). Reset the poll baseline.
4. If a model is in cooldown, do not leave it retrying; switch with `dt model --run` or stop the process.

If a single clean process still has no progress evidence after another quiet-round cap, pause and report (pids, snapshot-git or not, footer vs stream model).

## Container rebuild is trigger work

Bullet often lives **inside** the workspace container (`docker exec` hop in `run_*`).
It must not recreate, replace, stop, or `docker run` that container: that kills its own pane.

If bullet says the container is gone, stale, needs a new image, or asks to rebuild:

1. Do **not** `tmux send-keys` docker rebuild into `run_*`.
2. Trigger does it on the **Client / Server host**, outside that container.
3. After the new container exists, `dt re <dt>` (or rewrite `runtime.cmd`) and resume bullet with `--auto -s <id>` in the new pane.

Host-level docker/ssh is trigger. In-container coding is bullet.

## Architecture and flow → bullet mermaid, filed

If the work is **architecture**, **data/control flow**, **handoff between services**, or **how a request moves**, trigger does **not** write prose diagrams in `op_*`.

Dispatch to bullet (`tmux send-keys -t <run_*>`) and require:

1. **Mermaid** (`flowchart` / `sequenceDiagram` / `stateDiagram`) for the structure and the flow.
2. **File it in the workspace** (markdown next to the code, e.g. `docs/` or the feature dir). Do not leave it only in the chat.
3. Poll until the file exists; then continue.

Trigger may rephrase the ask. Trigger must not substitute ASCII/prose for the mermaid file.
