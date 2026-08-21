# Trigger vs bullet: who may touch the container

Bullet OpenCode often runs **inside** the workspace container (`run_*` hopped with `docker exec`).
Trigger OpenCode runs on the **Client**, outside that container (`op_*` → `~/.dual-tmux/ops/<op_*>`).

## Rule

If the workspace container must be created, replaced, rebuilt, or stopped, **trigger does it**.
Bullet must not. Recreating the box it is sitting in kills its own pane and sqlite.

| Action | Who |
|--------|-----|
| Edit code, run tests, in-container tools | bullet (`tmux send-keys -t run_*`) |
| `docker build` / `docker run` / replace that workspace container | trigger on Client or Server **host** |
| After a new container exists | trigger: `dt re <dt>`, then resume bullet `--auto -s <id>` |

## What trigger does when bullet asks to rebuild

1. Do not send docker rebuild into `run_*`.
2. On the host: build/run the new container (same workflow you already use).
3. Point `runtime.cmd` at the new name if it changed; `dt re <dt>`.
4. In the new pane: `opencode --auto -s <bullet-session-id>` (or `dt resume`).

Packaged skills (`tmux-trigger`, `dual-tmux`) and `ops/<op_*>/AGENTS.md` repeat this so trigger sessions read it on launch.
