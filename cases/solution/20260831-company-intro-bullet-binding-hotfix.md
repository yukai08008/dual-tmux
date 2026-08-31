# dt-company_intro_v2 bullet binding hotfix

## Code fix

- Remote freeze now requires a live remote OpenCode process and binds by its explicit session ID, or by its verified process cwd.
- It never falls back to the newest unrelated remote database session.
- A disconnected shell is not treated as a live SSH transport.
- Direct SSH process discovery preserves the exact reconnect command and port, and does not copy the local tmux cwd into `runtime.directory`.
- A fresh blank OpenCode TUI cannot bind an older session merely because both use the same cwd; freeze waits for a session created after the Agent process started.

## Data repair correction

The original tmux entry is authoritative: `ssh -oPort=24500 root@106.75.97.247`. Cross-checking the business host revealed the second hop, container `me_andy_browser`, and its original OpenCode session `nimble-cactus` (`ses_fb37c74b8ffe9VH0RIKOSZfQJW`) in `/root/intro_v2`.

The earlier attempt to create a fresh local bullet was incorrect and was superseded. The final repaired path is:

```text
run_company_intro_v2
  -> root@106.75.97.247:24500
  -> me_andy_browser
  -> /root/intro_v2
  -> ses_fb37c74b8ffe9VH0RIKOSZfQJW
```

`freeze` now records this canonical runtime point instead of the local trigger machine cwd. Hub and local records match, and all health layers pass.
