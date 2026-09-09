# 2026-09-09: Renewing owner never serves handoff

## Symptom

`dt resume dt-company_intro_v2` twice returned:

```text
[err] handoff timed out before the old Trigger was persisted and parked; ownership was not changed
```

The foreign `tm_ouc` owner renewed its four-second Lease continuously, while its
ownership evidence stopped updating for more than 100 minutes. Handoff requests
reached the Hub and expired as `claimant_timeout`; the owner emitted no persist,
reject, commit, park, or transfer event.

## Cause

The independent Lease worker remained healthy after the serial ownership worker
stalled in an earlier runtime probe. This advertised a live owner indefinitely,
although the control path responsible for handoff could no longer run.

The ten-second fault reservation was also too short for a bounded remote writer
probe plus cleanup and commit.
