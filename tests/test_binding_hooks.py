import pytest

from datanode.fsm_core import MemoryStateStore
from datanode.models import (
    AgentRole,
    BindingAttemptNode,
    BindingAttemptState,
    BindingIntent,
)
from datanode.runtime_fsm import (
    BindingEvent,
    BindingMachine,
    TunnelProjectionHook,
)
from dual_tmux.oc import empty_side


def _data():
    return {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": {**empty_side(), "session_id": "ses_trig_1"},
        "bullet": {**empty_side(), "session_id": "ses_bull_1"},
        "runtime": {
            "server": "root@box",
            "container": "c1",
            "directory": "/ws",
            "cmd": "ssh root@box",
        },
    }


def test_tunnel_projection_hook_updates_target_and_persists_entry():
    target = _data()
    working = _data()
    working["bullet"]["session_id"] = "ses_bull_2"
    working["runtime"]["directory"] = "/new_ws"
    working["runtime"]["cmd"] = "ssh root@box -p 2200"

    persisted_entries = []

    hook = TunnelProjectionHook(
        target=target,
        working=working,
        side="bullet",
        holder="tm_test",
        persist_entry_fn=lambda r, c: persisted_entries.append((r, c)),
    )
    hook.execute()

    assert target["bullet"]["session_id"] == "ses_bull_2"
    assert target["bullet"]["bound_by_client"] == "tm_test"
    assert target["runtime"]["directory"] == "/new_ws"
    assert len(persisted_entries) == 1
    assert persisted_entries[0][0] == "run_test"
    assert "/new_ws" in persisted_entries[0][1]
    assert target["runtime"]["cmd"] == persisted_entries[0][1]


def test_binding_machine_commit_proven_executes_hooks_and_binds():
    target = _data()
    working = _data()
    working["bullet"]["session_id"] = "ses_bull_rebuild"

    node = BindingAttemptNode(
        attempt_id="bind-test-1",
        tunnel_name="dt-test",
        role=AgentRole.BULLET,
        intent=BindingIntent.REBUILD,
        holder="tm_test",
    )
    machine = BindingMachine.create(node, MemoryStateStore())
    machine.send(
        BindingEvent.REQUESTED,
        {"holder": "tm_test", "local_mode": True, "occupancy_holder": ""},
    )
    assert machine.state is BindingAttemptState.PROVING

    hook_runs = []

    def audit_hook(_node, _ctx):
        hook_runs.append("audit")

    proj_hook = TunnelProjectionHook(
        target=target,
        working=working,
        side="bullet",
        holder="tm_test",
    )

    machine.register_commit_hook(audit_hook)
    machine.register_commit_hook(proj_hook)

    payload = {
        "session_id": "ses_bull_rebuild",
        "tool": "opencode",
        "directory": "/ws",
        "other_session_id": "ses_trig_1",
        "rebuild": True,
    }
    machine.commit_proven(payload)

    assert machine.state is BindingAttemptState.BOUND
    assert hook_runs == ["audit"]
    assert target["bullet"]["session_id"] == "ses_bull_rebuild"


def test_binding_machine_commit_proven_fails_closed_on_hook_error():
    target = _data()
    node = BindingAttemptNode(
        attempt_id="bind-test-2",
        tunnel_name="dt-test",
        role=AgentRole.BULLET,
        intent=BindingIntent.FREEZE,
        holder="tm_test",
    )
    machine = BindingMachine.create(node, MemoryStateStore())
    machine.send(
        BindingEvent.REQUESTED,
        {"holder": "tm_test", "local_mode": True, "occupancy_holder": ""},
    )

    def failing_hook(_node, _ctx):
        raise OSError("disk IO error during commit")

    machine.register_commit_hook(failing_hook)

    payload = {
        "session_id": "ses_bull_new",
        "tool": "opencode",
        "directory": "/ws",
        "other_session_id": "ses_trig_1",
        "rebuild": False,
    }
    with pytest.raises(OSError, match="disk IO error"):
        machine.commit_proven(payload)

    assert machine.state is BindingAttemptState.FAILED
    assert "disk IO error" in machine.node.error
    # Target was not modified
    assert target["bullet"]["session_id"] == "ses_bull_1"
