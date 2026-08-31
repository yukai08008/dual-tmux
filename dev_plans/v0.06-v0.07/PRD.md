# v0.07 PRD — Local-first configuration and safe Hub migration

> Parent: v0.06 / package v0.4.38
> Drafted: 2026-08-31
> Type: API (odd)
> Source: user request

## 0. Goal

Allow dual-tmux to work with only a local Client identity, and let a user later attach, replace, or detach a synchronization Hub without losing tunnel records.

## 1. Scope and invariants

### 1.1 In scope

- A local-only config requires only `client`; Hub `server` and `user` are absent.
- Existing config files containing `client`, `server`, and `user` remain Hub configs without migration.
- Hub operations and distributed locks become optional capabilities.
- Attaching or replacing a Hub performs merge-sync before the new config is committed.
- Detaching a Hub pulls/merges its final state before local mode is committed.
- A local tunnel starts its bullet on this machine instead of constructing an SSH command.

### 1.2 Out of scope

- Deletion propagation between Clients.
- Multiple simultaneous Hubs or Hub history in config.
- Cross-client lock semantics while local-only.
- Resumable Codex/Claude sessions.

### 1.3 Invariants

- Switching configuration never deletes local or remote tunnel/entry files.
- A failed preflight leaves the old config unchanged.
- Merge conflict resolution continues to use `updated_at` plus deterministic SHA-256 tie-breaking.
- Runtime data under `data/` is not tracked by Git.
- Existing Hub users see no behavior change.
- New user-facing setup behavior is covered by CLI-level automated tests; Web behavior remains unchanged.

## 2. Blueprint

```text
local-only                     attach / replace Hub
config(client)                 candidate(client, server, user)
     |                                      |
     +-- local tmux + local records         +-- sync old Hub (when present)
     +-- tick samples locally               +-- merge local <-> candidate Hub
     +-- no ssh/rsync/remote lock            +-- atomically write candidate config

Hub config                     detach to local
     |                                      |
     +-- existing behavior                  +-- final merge from current Hub
                                            +-- write local-only config
                                            +-- remove persist sync cron entries
```

## 3. Configuration model

`AppConfig.hub_enabled` is derived from a valid `(server, user)` pair. The serialized format needs no schema version. Empty Hub fields mean local-only; the legacy placeholders `server` / `user` are treated as unconfigured.

Partial Hub configuration is invalid. Environment overrides follow the same rule.

## 4. Migration transaction

1. Validate candidate locally.
2. If changing/detaching an existing Hub, merge-sync it into local state.
3. If attaching/changing, merge-sync local state with the candidate Hub.
4. Only after successful sync, write `config.toml` using atomic replace.
5. Reconcile cron/hotfix state for the resulting mode.

Remote writes are additive merge results. If step 3 succeeds but config writing fails, the candidate merely holds an additional recoverable copy; local state and old config remain intact.

## 5. Risk register

| ID | Severity | Risk | Mitigation | Owner |
|---|---|---|---|---|
| R1 | high | Empty server still generates `ssh server` | Explicit local runtime command and tests | Coder |
| R2 | high | Switching publishes stale local state | Sync old Hub first, then candidate | Coder |
| R3 | high | Old persist cron keeps syncing after detach | Remove only `dt-persist-*` cron lines | Coder |
| R4 | medium | Partial config silently disables sync | Reject server/user partial pairs | Coder |
| R5 | medium | Existing configs change behavior | Backward-compat parsing tests | Tester |

## 6. Signature

Agent-PM-0.07
