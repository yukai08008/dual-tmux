# 2026-09-09: Stalled handoff control-plane recovery

## Safety proof

A renewing owner may be fenced after a cooperative handoff timeout only when all
of these facts hold under the same Hub generation:

1. Lease v2 evidence is older than five minutes.
2. The same claimant's handoff ended as `claimant_timeout`, and the request was
   created after the last evidence sample.
3. The latest owner OpenCode snapshot is pulled and its update time covers the
   Trigger's last recorded semantic change.
4. The remote bullet process can be inspected and fenced before ownership commit.

The Hub then records a `fencing` reservation under its flock. This makes the old
owner's next exact-generation renewal fail, causing its Lease worker to park the
local Trigger after observing the higher generation. Reservation lifetime is 30
seconds so the bounded remote cleanup can finish.

Ordinary handoff timeout, fresh evidence, a different claimant, missing snapshot
coverage, unknown remote cleanup, and generation changes remain fail-closed.

The daemon ownership loop now catches per-step probe/parser failures and continues
instead of dying while the independent Lease loop keeps renewing forever.
