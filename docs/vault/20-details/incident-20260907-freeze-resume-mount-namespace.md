---
id: incident-20260907-freeze-resume-mount-namespace
type: incident
status: resolved
updated: 2026-09-07
tags: [dual-tmux, incident, freeze, resume, opencode, docker, mount-namespace]
part_of:
  - "[[10-summaries/session-ownership|Session Ownership]]"
related:
  - "[[20-details/incident-20260902-lockscreen-lease|锁屏租约误判与有副作用的 resume 拒绝]]"
---

# 2026-09-07 - Live OpenCode 被 freeze/resume 误判为不存在

## Summary

`dt work` 能进入 `run_new_event_v2`，pane 中 OpenCode 1.18.29 正常运行，
但 `dt freeze` 报 `no bullet opencode`；完成 freeze 修复后，`dt resume`
又报 `resume writer verification failed: trigger,bullet`。

两个错误都不是 tmux session 不存在，而是探测逻辑没有覆盖 OpenCode 的
mount namespace 和首次裸启动行为。

## Symptoms

```text
$ dt freeze
! no bullet opencode on run_new_event_v2 (cmd=ssh cwd=/workspace).
[err] freeze failed for bullet; successful sides were kept

$ dt work
[detached (from session run_new_event_v2)]

$ dt resume dt-new-event-v2
skip remote bullet TUI is live; persist recovery not needed
skip op_new_event_v2 already running opencode
skip run_new_event_v2 bullet TUI already attached; not starting a duplicate
[err] resume writer verification failed: trigger,bullet
```

`[detached (from session ...)]` 是正常 tmux detach，不表示 `dt work` 或
`run_new_event_v2` 不存在。

## Runtime topology

- Local pane: `run_new_event_v2`
- Local pane command: `ssh root@10.89.0.15`
- Remote OpenCode cwd: `/workspace`
- Remote OpenCode argv: `opencode --auto`
- OpenCode process actually runs in a Docker mount namespace.
- Tunnel runtime only records the SSH host; it has no container name.

The host can see the process through `/proc`, but the host and the process do
not share the same filesystem view:

```text
/proc/<pid>/ns/mnt   !=   /proc/self/ns/mnt
```

The OpenCode process sees:

```text
/root/.opencode/bin/opencode
/root/.local/share/opencode/opencode.db
```

Those paths are absent from the ordinary non-interactive SSH shell. They are
reachable from the host through:

```text
/proc/<pid>/root/root/.opencode/bin/opencode
/proc/<pid>/root/root/.local/share/opencode/opencode.db
```

## Root causes

### Freeze false negative

`active_remote()` found the live OpenCode process in host `/proc`, but always
opened the probing shell's `$HOME/.local/share/opencode/opencode.db`. Because
the database only existed inside the process mount namespace, freeze returned
no session.

The same namespace mismatch made the non-interactive client version probe
return exit 127 even though OpenCode 1.18.29 was live.

### Resume writer false negative

Both OpenCode TUIs were initially started without `-s`:

```text
opencode
opencode --auto
```

OpenCode created each session lazily after the first prompt. The live process
argv therefore never contained the resulting session ID. Writer verification
only searched process command lines for that ID and reported `count=0` for
both sides.

## Repair

### Namespace-aware remote discovery

For every live OpenCode PID:

1. Read `/proc/<pid>/environ` for `OPENCODE_DB` and `HOME`.
2. Resolve absolute database paths through `/proc/<pid>/root`.
3. Query that PID's own OpenCode database for its exact cwd/session.
4. If non-interactive `PATH` cannot find OpenCode, resolve `/proc/<pid>/exe`,
   execute it through `/proc/<pid>/root`, and retain the logical executable
   path in metadata.

### Session-aware writer verification

Keep command-line session matching as the first, strict check. When it returns
zero writers for OpenCode, use the current pane plus OpenCode sqlite as a
fallback. Count one writer only when the live session ID exactly equals the
frozen tunnel session ID. A different or unprovable session remains zero, so
the ownership gate stays fail-closed.

## Verification

After the repair:

```text
$ dt freeze
bullet  client=opencode@1.18.29
model=xs-cp-gate/gpt-5.6-sol
session=ses_f84bcce1dffedBN9L5La5dhV47
ok  freeze dt-new-event-v2  IS_DST=yes
```

Writer probes returned exactly one writer per side:

```text
trigger: status=ok count=1
bullet:  status=ok count=1
```

The full v0.4.54 test suite passed, including regressions for namespace-aware
database discovery, live executable discovery, exact-session writer fallback,
and rejection of a different live session.

## Operational notes

- `dt upgrade` installs the published GitHub release. If a local uncommitted
  hotfix has been installed with `uv tool install --force --from ...`, upgrade
  replaces it with the published build.
- A visible TUI is evidence of process liveness, not by itself proof of the
  session identity required by freeze or ownership verification.
- Do not infer remote OpenCode availability only from non-interactive `PATH`
  or from filesystem paths visible in the SSH login namespace.
