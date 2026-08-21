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
