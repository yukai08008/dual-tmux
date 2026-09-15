---
name: tmux-trigger
description: Trigger agent dispatches work into the bullet OpenCode in run_* via dt send, checks dt bullet state before acting, polls on real progress evidence with a quiet-round cap, and recovers with dt rebuild. Never wrap the task in ssh/docker exec -it.
trigger: When dispatching work, polling a bullet, checking bullet state, recovering a stuck bullet, or the user says 派活 / 放手 / trigger-bullet.
---

# tmux trigger

You are **trigger**. The task process must live in the **bullet** pane (`run_*`), not on your SSH.

## Responsibilities

Trigger owns supervision of the delegated task on the user's behalf:

1. Dispatch a scoped task to bullet with enough context, likely file paths, and
   acceptance criteria for it to work autonomously.
2. Poll bullet without requiring the user to ask for updates. Track material
   progress, blockers, test results, and completion, then report meaningful
   changes back to the user.
3. Assess whether bullet is progressing, legitimately busy, blocked, or likely
   stalled. A quiet pane alone is not proof of failure; use elapsed time,
   repeated captures, process activity, and the expected operation together.
4. Keep the task moving. Narrow unclear work, provide missing context, interrupt
   a genuinely stuck turn, recover the pane/session when needed, and continue
   supervision until the requested result is complete or a real blocker needs
   the user's decision.

Dispatch is not fire-and-forget. Trigger remains accountable for bullet's
progress and recovery; bullet remains accountable for execution in the workspace.

```
派活 → 放手 → 轮询 → 再贴回去看
```

## Forbidden

```sh
ssh -t <server> 'docker exec -it <container> opencode run ...'
ssh -t <server> 'docker exec -it ... opencode --auto -s ses_xxx'
```

`docker exec -it` dies with SIGHUP when SSH drops.

## State and events before acting

Before dispatching, interrupting, or recovering, check the factual snapshot once:

```sh
dt bullet <dt> --json
```

It reports per-side activity state (working/idle/stalled with no-progress seconds),
health, transport pane command, remote writer count, and the last bullet events —
without touching the bullet pane. Gate your action on `hint`:

- `ok_to_dispatch` — send the task.
- `working_wait_for_turn_end` — do not queue another message; poll instead.
- `stalled_no_progress_<N>s_do_not_queue` — stop stacking messages; run the recovery below.
- `multiple_writers_fence_first_dt_rebuild` — orphan instances hold the session; rebuild.
- `transport_down_dt_rebuild` — the jump is gone; rebuild reconnects it.
- `probe_failing_check_dt_health` — run `dt health <dt>` before acting.

For history (what you or the user did to this bullet recently):

```sh
dt log --name <dt> --cat bullet -n 10
```

## Dispatch

1. `dt bullet <dt> --json` — gate on `hint` as above.
2. If the pane is shell/transport is down: `dt rebuild <dt>` (repairs the jump and starts bullet with the bound session).
3. If bullet is already a live `--auto` OpenCode: `dt send <dt> 'task...'` — it is occupancy-guarded and recorded as a `bullet.send` event. Use raw `tmux send-keys -t <run_*>` only if the `dt` CLI is unavailable.
4. Poll as below. Do not hold an SSH session as the task lifecycle.

Resume bullet through `dt rebuild <dt>` (bound session, fenced start), never hand-typed `opencode --auto -s`, and never `-c`. `dt rebuild` verifies zero leftover opencode processes before starting; Escape / Ctrl+C does not count as dead.

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

1. Run `dt bullet <dt> --json`. Multiple writers, stalled state, or a dead transport all map to one action.
2. Run `dt rebuild <dt>`. It repairs the route, reconnects the jump, kills every remote process bound to the bullet session (including snapshot-git spinners), imports the remote persist snapshot when needed, and restarts exactly one bullet with the bound session id. Every step is recorded in `dt log --name <dt> --cat bullet`. Refuses to kill a `working` bullet unless you pass `--force`.
3. Reset the poll baseline and continue supervision.
4. If a model is in cooldown, do not leave it retrying; switch with `dt model --run` or stop the process.

If a single clean process still has no progress evidence after another quiet-round cap, pause and report (pids, snapshot-git or not, footer vs stream model).

## Model changes are not session changes

Treat changing a model and creating a session as independent operations.

- By default, preserve the current bullet session and change the model inside
  its live OpenCode TUI with `/models` (or `Ctrl+x m`). Use `tmux send-keys` to
  open the selector, search for the exact `provider/model`, and confirm it.
- Switch while bullet is idle, or interrupt the current turn only when the user
  explicitly wants that turn stopped. The selected model applies to subsequent
  turns in the same session.
- Verify the TUI footer/header shows the requested model, then run
  `dt freeze <dt> --bullet` so the binding records the new model while retaining
  the same session ID. Report both the model and session ID after verification.
- Treat tunnel JSON as the last frozen snapshot, not a live source of truth.
  When state may have changed, run bullet freeze and verify the resulting
  session against the current `run_*` pane. The live probe filters OpenCode
  processes to the current SSH connection window and reads the actual model
  from the session's latest user/assistant message; do not infer it from the
  global `opencode.json` default or a stale session-table model.
- Do not use `dt model` for an ordinary model switch: its current implementation
  exits/fences OpenCode and starts `opencode --model ...`, which creates and
  binds a new session.
- Use `dt model` only when the user explicitly asks for a fresh session together
  with the model change. Never silently replace conversation continuity.

## Supervise with an estimate

Estimate the wall-clock time before dispatch, then use that estimate to decide
whether the bullet is progressing. Do not poll forever at a fixed interval.

| Size | Typical work | Expected | Investigate when there is no material progress |
|---|---|---|---|
| S | one value, message, or local edit | 2-8 min | 3-4 min or two unchanged captures |
| M | connect an existing path, edit a few files | 10-25 min | about 12 min or three unchanged captures |
| L | new subsystem, page, or workflow | 30-60 min | halfway through the estimate with no diff or test progress |

For S/M work, dispatch with 2-3 likely file paths and a narrow acceptance
criterion. Avoid unbounded repository scans and new abstractions unless the
task actually requires discovery or design. If actual behavior is a size larger
than estimated, treat it as scope expansion and narrow the task immediately.

### Detect stalls, not merely quiet panes

Compare captures for material progress: a new tool, file, diff, test phase, or
completion message. Repeatedly seeing the same `Grep`, `Read`, `Thinking`, or
`QUEUED` line is a stall signal, but not proof by itself.

1. After two unchanged captures, reassess the estimate, scope, and current tool.
2. After three unchanged captures with no supporting process activity, send a
   shorter instruction with exact paths and acceptance criteria.
3. If the current turn is still stuck, interrupt with Escape. If that does not
   settle it, run `dt rebuild <dt>`; never use `-c`.

Long tests, builds, downloads, and network calls may legitimately leave the pane
unchanged. Check process activity or expected timeout before interrupting them.
`--auto` is serial: a `QUEUED` message does not unblock a stalled current turn.

Poll active S work every 20-30s and M/L work around every 30s. Shorten the next
check after an unchanged capture; do not call a longer 90-120s sleep an
adjustment.

## Container rebuild is trigger work

Bullet often lives **inside** the workspace container (`docker exec` hop in `run_*`).
It must not recreate, replace, stop, or `docker run` that container: that kills its own pane.

If bullet says the container is gone, stale, needs a new image, or asks to rebuild:

1. Do **not** `tmux send-keys` docker rebuild into `run_*`.
2. Trigger does it on the **Client / Server host**, outside that container.
3. After the new container exists, `dt rebuild <dt>` (or rewrite `runtime.cmd` first); it reconnects the new pane and resumes bullet with the bound session id.

Host-level docker/ssh is trigger. In-container coding is bullet.

## Architecture and flow → bullet mermaid, filed

If the work is **architecture**, **data/control flow**, **handoff between services**, or **how a request moves**, trigger does **not** write prose diagrams in `op_*`.

Dispatch to bullet (`tmux send-keys -t <run_*>`) and require:

1. **Mermaid** (`flowchart` / `sequenceDiagram` / `stateDiagram`) for the structure and the flow.
2. **File it in the workspace** (markdown next to the code, e.g. `docs/` or the feature dir). Do not leave it only in the chat.
3. Poll until the file exists; then continue.

Trigger may rephrase the ask. Trigger must not substitute ASCII/prose for the mermaid file.
