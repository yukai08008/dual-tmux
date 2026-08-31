# dt-company_intro_v2 bullet false remote binding

## Background

`run_company_intro_v2` historically ran OpenCode locally. That Agent used an inner SSH command to operate `106.75.97.247:24500`. `tom7r` was only the dual-tmux Hub.

## Symptom

Resume replayed `ssh -t tom7r "cd /Users/andy && exec bash"`. `/Users/andy` does not exist on tom7r, SSH exited, and the OpenCode resume command was then typed into the local shell.

## Evidence

- tmux persist records the original inner hop as `ssh -oPort=24500 root@106.75.97.247`.
- tom7r has no matching OpenCode session.
- the target business host has no OpenCode executable.
- the recorded `happy-circuit` session is a one-message smoke session also bound to another tunnel.

## Root cause

Freeze could query the latest session from a remote database without proving a live remote OpenCode process. A disconnected SSH pane could also expose its local cwd, which was then written as a remote directory.
