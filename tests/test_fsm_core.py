from enum import Enum

import pytest

from datanode.fsm_core import (
    FileStateStore,
    Graph,
    Machine,
    MemoryStateStore,
    StateStore,
    TransitionError,
)


class State(str, Enum):
    IDLE = "idle"
    READY = "ready"


def test_transition_order_and_log():
    calls = []
    graph = Graph(
        {
            (State.IDLE, State.READY): {
                "event": "prepare",
                "guard": lambda ctx: calls.append("guard") or ctx["valid"],
                "on_exit": lambda ctx: calls.append("exit"),
                "on_enter": lambda ctx: calls.append("enter"),
            }
        },
        initial=State.IDLE,
    )
    machine = Machine(graph, context={"valid": True})

    assert machine.send("prepare") == State.READY
    assert calls == ["guard", "exit", "enter"]
    assert machine.log[0] | {"ts": 0} == {
        "from": "idle",
        "to": "ready",
        "event": "prepare",
        "ts": 0,
    }


def test_guard_and_illegal_event_preserve_state_and_log():
    graph = Graph(
        {
            (State.IDLE, State.READY): {
                "event": "prepare",
                "guard": lambda ctx: False,
            }
        },
        initial=State.IDLE,
    )
    machine = Machine(graph)

    with pytest.raises(TransitionError, match="guard rejected"):
        machine.send("prepare")
    with pytest.raises(TransitionError, match="available events"):
        machine.send("unknown")
    assert machine.state == State.IDLE
    assert machine.log == []


def test_memory_store_is_a_copying_state_store():
    store = MemoryStateStore()
    assert isinstance(store, StateStore)
    snapshot = {"state": "idle", "node": {"count": 1}}
    store.save("node-1", snapshot)
    snapshot["node"]["count"] = 2
    loaded = store.load("node-1")
    assert loaded == {"state": "idle", "node": {"count": 1}}
    loaded["node"]["count"] = 3
    assert store.load("node-1")["node"]["count"] == 1


def test_file_store_round_trip(tmp_path):
    store = FileStateStore(tmp_path)
    snapshot = {"schema_version": 1, "state": "ready", "node": {"id": "n-1"}}
    store.save("n-1", snapshot)
    assert store.exists("n-1")
    assert store.load("n-1") == snapshot
    assert store.list_keys() == ["n-1"]
    assert store.delete("n-1") is True
    assert store.load("n-1") is None
