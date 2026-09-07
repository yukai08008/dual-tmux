# v0.4.53 API Freeze

> Freeze date: 2026-09-07  
> Implementation merge: PR #31 / `e7e64f7`

## Frozen contracts

- Native persist root: `~/sessions/native/<source>/<tool>/<session-id>/`.
- Supported native tools: `codex`, `claude`.
- `active.json` and `revisions/<sha256>/manifest.json` use schema 1 and must be identical.
- One manifest contains exactly one safe relative `.jsonl` payload with size and SHA-256.
- Revision equals payload SHA-256; histories may converge only by byte-prefix ancestry.
- Ownership facts add `native_snapshots.trigger` and `.bullet`, each exposing `status`, `tool`, and `session_id`.
- Status values: `missing`, `local`, `hub`, `newer`, `conflict`, `unsupported`.
- Handoff preserves export → durable sync → live revision verify → park → ack → release.
- Native import validates identity/hash, commits atomically, preserves UUID, and is fenced by lease generation.

## Compatibility

- Lease v2 schema and OpenCode snapshot contracts from v0.4.51 are unchanged.
- v0.4.51 owners reject native handoff using their existing unsupported reason.
- v0.4.53 claimants never start a native writer when no valid snapshot/local session exists.
- Runtime payloads remain outside Git and under the existing Hub user namespace.

Any incompatible change requires a later odd API version; v0.4.54 Web must consume this contract without redefining it.
