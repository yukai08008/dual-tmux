---
name: tmux-trigger
description: Trigger agent dispatches work into the bullet OpenCode in run_* via tmux send-keys, then polls. Never wrap the task in ssh/docker exec -it.
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
4. Poll every 15–30s. Do not hold an SSH session as the task lifecycle.

Resume bullet with `opencode --auto -s <id>`, never `-c`.

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
