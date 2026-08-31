# Local web console (design)

CLI is enough for **one** tunnel. The web exists because there are **many** line-heads: you cannot scan op/run output, type the next send, and keep context if you have to `dt enter` / `dt work` one at a time.

```sh
dt web                 # 127.0.0.1 only, default :8787; opens the default browser
dt web --no-open       # headless use: print URL without opening a browser
```

Admin layout: **left tabs** (Dashboard, 隧道), **right content**. Same Client, same `~/.dual-tmux/`, same tmux. Not a second hub.

## v1 is the panes

Yes: **terminal input and output through the page** is the first feature, not freeze buttons.

Each tunnel has two panes: `op_*` (trigger) and `run_*` (bullet). For each pane the page must:

| Direction | How |
|-----------|-----|
| Output | `tmux capture-pane -p` on a short poll (or websocket later). Show last N lines, auto-scroll, pick tunnel without losing the others. |
| Input | textarea → `tmux send-keys` into that pane (`dt send` for run; same primitive for op). Enter sends. |

This is how you **monitor, manage, and advance many projects**: you read what trigger/bullet just printed, you type the next instruction, you switch tunnels in the left list. You do not attach.

### Honest limit (OpenCode TUI)

OpenCode in the pane is a full TUI (alt screen, keys like `C-x`). Capture-pane gives a **text snapshot**; send-keys can paste a prompt into `--auto` / a waiting TUI. It is **not** a perfect xterm clone (no mouse, no reliable resize, redraws can look messy).

v1 still ships capture + send-keys because that matches how trigger already works (`tmux send-keys -t run_*`). If a pane needs real attach, the page shows `dt enter` / `dt work` as escape hatch — not as the default.

Do **not** defer the pane UI. Do **not** start with a card board that only lists JSON.

## Layout

```
┌─────────────┬──────────────────────────────────────────────┐
│ dt web      │  dt-portal                          [op|run] │
│             │  ┌─────────────────────────────────────────┐ │
│ Tunnels  ●  │  │  pane output (capture, live)            │ │
│ Memory      │  │                                         │ │
│ Events      │  └─────────────────────────────────────────┘ │
│ Doctor      │  ┌─────────────────────────────────────────┐ │
│             │  │  input  (send-keys to selected pane)    │ │
│ dt-msg      │  └─────────────────────────────────────────┘ │
│ dt-msg2     │  meta: DST / model / lock / jump  (compact)  │
│ dt-portal ← │                                              │
└─────────────┴──────────────────────────────────────────────┘
```

- Left **Tunnels**: every DT, live dot (tmux up?), IS_DST, last activity. Click = right pane pair.
- Right default: **that tunnel’s I/O**. Toggle op vs run (or split view later).
- Browser workspace tabs, their selected tunnel, Q&A thread, and compact poll log are kept in
  `~/.dual-tmux/web-state.json` and restored after a refresh or browser change. Closing a tab keeps
  its visit record and latest trigger Q&A; **最近访问** reopens it with that context. Pane snapshots
  remain live data and are polled again.
- The tunnel catalog is refreshed from `/api/tunnels` every five seconds and whenever search gains
  focus, so DTs created after the page opened appear without a full browser reload.
- Selecting an offline DST automatically runs the non-attaching resume path. It obeys the normal
  hub lock and never forces takeover; ordinary DTs are not started automatically.
- The **指南** tab groups common workflows and provides a command reference. All pages share an
  inline SVG favicon, so the local console is identifiable in browser tabs without static assets.
- Trigger Q&A follows new messages only while its scrollbar is already near the bottom, preserving
  the reader's position while reviewing older turns. A non-`auto` OpenCode pane stops the web poll
  with a manual-action message, and every submitted turn has a 90-second polling ceiling.
- When an online trigger is not in auto mode, the tunnel page offers **trigger 转为 auto**. It exits
  that pane's current OpenCode process and resumes the frozen trigger session with `--auto -s`; it
  never creates a replacement session ID.
- Other left tabs (Memory / Events / Doctor) are secondary. Lifecycle (freeze, resume, re) lives as a small bar on the tunnel page, **after** I/O works.

## Full control plane (v0.4.46)

The tunnel page now covers the daily business control loop without a terminal:

- create a local or Hub-backed tunnel and choose OpenCode, Codex, or Claude per side;
- send/capture pane I/O, freeze selected sides, resume, replay the authoritative entry, and drop local panes;
- push/pull Hub records, run a health probe, recover explicitly, and toggle conservative auto recovery;
- switch local/Hub mode through the same merge-before-commit transaction as the CLI;
- remove a tunnel only after typing its exact name.

Capability data disables OpenCode-only model controls for Codex/Claude. GET polling remains read-only. Host-maintenance commands (`upgrade`, `hotfix`, cron installation) stay CLI-only because a local web page should not silently mutate its own software supply chain or host scheduler.

## Must not

- Bind anything but `127.0.0.1` in v1
- Touch `~/.ssh` or OpenCode sqlite
- Replace tmux as the process host (web is a window onto existing panes)
- Rebuild the workspace container from the bullet input box

## Stack when we build

`dt web` in this package (stdlib `ThreadingHTTPServer`). Capture + send-keys via existing `tmux` helpers. Poll `/api/pane` every 1.5s.
