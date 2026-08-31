# dt-company_intro_v2 bullet binding hotfix

## Code fix

- Remote freeze now requires a live remote OpenCode process and binds by its explicit session ID, or by its verified process cwd.
- It never falls back to the newest unrelated remote database session.
- A disconnected shell is not treated as a live SSH transport.
- Direct SSH process discovery preserves the exact reconnect command and port, and does not copy the local tmux cwd into `runtime.directory`.
- A fresh blank OpenCode TUI cannot bind an older session merely because both use the same cwd; freeze waits for a session created after the Agent process started.

## Data repair

Create a fresh local OpenCode bullet for `dt-company_intro_v2`, freeze it from the live pane, and let freeze atomically rewrite the tunnel as local runtime. Preserve the trigger session and synchronize the repaired binding to the Hub.

The repaired bullet is `happy-canyon` (`ses_fa9af64d6ffeGtQF6grUPvWlTJ`). A controlled Agent exit followed by `dt recover --now` restored this exact session and its `READY` conversation; all health layers passed.
