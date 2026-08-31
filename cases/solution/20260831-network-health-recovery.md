# Conservative layered health and recovery

## Decision

Probe structural layers from `dt tick`, persist a local cache, and require explicit per-tunnel `auto_recover` opt-in. Do not restart based on unchanged output.

## State machine

`healthy → suspect → degraded → recovering`; three consecutive failures gate recovery. Retries back off at 60/120/300/600/1800 seconds and five failed attempts open a circuit in `attention`.

## Safety properties

- acquire Hub ownership before recovery;
- use only the recorded host, container, and directory;
- import a missing remote OpenCode session only from an existing persist JSON;
- never clear session IDs, persist JSON, or the last healthy workpoint on failure;
- Web reads cached health only;
- local-only mode makes no SSH health calls.
