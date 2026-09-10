"""Stubs for removed Hub lease APIs so older tests can still monkeypatch them."""

from __future__ import annotations

import pytest

from dual_tmux import hub

_REMOVED = (
    "read_ownership",
    "renew_ownership",
    "request_handoff",
    "begin_handoff",
    "finish_handoff",
    "cancel_handoff",
    "claim_generation",
    "reserve_fault_takeover",
    "finish_fault_takeover",
    "cancel_fault_takeover",
    "decide_handoff",
)


@pytest.fixture(autouse=True)
def _removed_hub_lease_attrs():
    for name in _REMOVED:
        if not hasattr(hub, name):
            setattr(hub, name, lambda *_a, **_k: None)
