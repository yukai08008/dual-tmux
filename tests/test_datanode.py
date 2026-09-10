from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from datanode import (
    AgentRole,
    AgentSessionNode,
    DockerEndpointNode,
    LocalEndpointNode,
    OccupancyNode,
    OwnershipLeaseNode,
    PaneRuntimeNode,
    RuntimeEndpointNode,
    SnapshotRevisionNode,
    SshEndpointNode,
    TunnelNode,
    WriterEvidence,
    from_legacy_tunnel,
    occupancy_from_hub,
    ownership_from_hub,
    pane_from_ownership_facts,
    snapshot_from_revision,
    to_legacy_tunnel,
)

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)


def _sessions():
    return (
        AgentSessionNode(
            session_id="ses_trigger", role=AgentRole.TRIGGER, model="gpt-5.6-sol"
        ),
        AgentSessionNode(session_id="ses_bullet", role=AgentRole.BULLET),
    )


def test_valid_business_nodes_and_derived_local_command():
    trigger, bullet = _sessions()
    node = TunnelNode(
        name="dt-demo",
        op="op_demo",
        run="run_demo",
        endpoint=LocalEndpointNode(directory="/tmp/work"),
        trigger=trigger,
        bullet=bullet,
    )
    assert node.endpoint.identity == "local:/tmp/work"
    assert node.endpoint.reconnect_command == "cd /tmp/work"


def test_unknown_fields_and_bad_tunnel_names_are_rejected():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        LocalEndpointNode(directory="/tmp", typo=True)
    with pytest.raises(ValidationError):
        TunnelNode(
            name="demo",
            op="wrong",
            run="run_demo",
            endpoint=LocalEndpointNode(),
        )


def test_roles_and_session_identity_cannot_be_crossed():
    trigger, _ = _sessions()
    with pytest.raises(ValidationError, match="role=bullet"):
        TunnelNode(
            name="dt-demo",
            op="op_demo",
            run="run_demo",
            endpoint=LocalEndpointNode(),
            bullet=trigger,
        )
    with pytest.raises(ValidationError, match="same session"):
        TunnelNode(
            name="dt-demo",
            op="op_demo",
            run="run_demo",
            endpoint=LocalEndpointNode(),
            trigger=trigger,
            bullet=AgentSessionNode(
                session_id=trigger.session_id, role=AgentRole.BULLET
            ),
        )


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ({"kind": "local", "directory": "/tmp"}, "local"),
        ({"kind": "ssh", "server": "root@box", "port": 22}, "ssh"),
        (
            {
                "kind": "docker",
                "server": "root@box",
                "container": "agent",
                "directory": "/workspace",
            },
            "docker",
        ),
    ],
)
def test_endpoint_discriminated_union(raw, kind):
    endpoint = TypeAdapter(RuntimeEndpointNode).validate_python(raw)
    assert endpoint.kind == kind


def test_docker_requires_complete_location_and_derives_reconnect_command():
    with pytest.raises(ValidationError):
        DockerEndpointNode(server="", container="agent", directory="/workspace")
    endpoint = DockerEndpointNode(
        server="root@box", container="agent", directory="/workspace", port=2222
    )
    assert "ssh -t" in endpoint.reconnect_command
    assert "-p 2222" in endpoint.reconnect_command
    assert "docker exec -it agent" in endpoint.reconnect_command
    assert SshEndpointNode(server="box").kind == "ssh"


def test_occupancy_is_last_writer_without_ttl():
    node = OccupancyNode(tunnel_name="dt-a", holder="tm_here", generation=4)
    assert node.identity == "dt-a@4"
    assert node.is_foreign("tm_other") is True
    assert node.is_foreign("tm_here") is False
    mapped = occupancy_from_hub(
        {"name": "dt-a", "holder": "tm_home", "generation": 9, "claimed_at": 1}
    )
    assert mapped.holder == "tm_home"
    assert mapped.generation == 9
    assert mapped.claimed_at is not None


def test_active_v2_lease_requires_holder_and_instance_and_never_regresses():
    with pytest.raises(ValidationError, match="requires a holder"):
        OwnershipLeaseNode(tunnel_name="dt-a", generation=2, state="owned", protocol=2)
    with pytest.raises(ValidationError, match="instance_id"):
        OwnershipLeaseNode(
            tunnel_name="dt-a",
            generation=2,
            state="foreign",
            protocol=2,
            holder="tm_other",
        )
    old = OwnershipLeaseNode(
        tunnel_name="dt-a",
        generation=3,
        state="owned",
        protocol=2,
        holder="tm_here",
        instance_id="mac:one",
    )
    stale = old.model_copy(update={"generation": 2})
    assert not stale.succeeds(old)


def test_writer_evidence_and_pane_observation_keep_unknown_distinct_from_zero():
    with pytest.raises(ValidationError, match="number of PIDs"):
        WriterEvidence(status="ok", count=1, pids=())
    with pytest.raises(ValidationError, match="must not claim a count"):
        WriterEvidence(status="unknown", count=0)
    observation = PaneRuntimeNode(
        tunnel_name="dt-a",
        role="trigger",
        observed_at=NOW,
        tmux_session="op_a",
        runtime="unknown",
        attached=None,
        writers=WriterEvidence(status="unknown", count=None, reason="probe_failed"),
    )
    assert observation.attached is None
    assert observation.writers.count is None


def test_snapshot_tail_must_be_in_revision_messages():
    with pytest.raises(ValidationError, match="tail must be present"):
        SnapshotRevisionNode(
            session_id="ses_a",
            digest="a" * 64,
            updated_at=NOW,
            message_ids=frozenset({"msg_1"}),
            tail_message_id="msg_2",
        )


def test_legacy_unfrozen_tunnel_is_valid_and_round_trip_preserves_extensions():
    legacy = {
        "name": "dt-demo",
        "op": "op_demo",
        "run": "run_demo",
        "client": "tm_home",
        "user": "andy",
        "runtime": {
            "server": "root@box",
            "ssh_port": 24500,
            "container": "agent",
            "directory": "/workspace",
            "cmd": "stale command that must be re-derived",
        },
        "trigger": {"tool": "opencode", "session_id": ""},
        "bullet": {"tool": "opencode", "session_id": ""},
        "times": {"created_at": "2026-09-09T00:00:00+00:00"},
        "ownership_generation": 19,
        "updated_at": "2026-09-09T00:00:00+00:00",
    }
    node = from_legacy_tunnel(legacy)
    assert node.trigger is None and node.bullet is None
    assert node.endpoint.kind == "docker"

    restored = to_legacy_tunnel(node, base=legacy)
    assert restored["times"] == legacy["times"]
    assert restored["ownership_generation"] == 19
    assert restored["runtime"]["cmd"] == node.endpoint.reconnect_command
    assert restored["trigger"] == legacy["trigger"]


def test_legacy_frozen_tunnel_preserves_binding_semantics():
    legacy = {
        "name": "dt-frozen",
        "op": "op_frozen",
        "run": "run_frozen",
        "runtime": {"server": "", "directory": "/tmp/work"},
        "trigger": {
            "tool": "opencode",
            "session_id": "ses_trigger",
            "model": "gpt-5.6-sol",
            "custom_future_field": "keep",
        },
        "bullet": {"tool": "claude", "session_id": "session-b"},
    }
    node = from_legacy_tunnel(legacy)
    restored = to_legacy_tunnel(node, base=legacy)
    assert restored["trigger"]["session_id"] == "ses_trigger"
    assert restored["trigger"]["custom_future_field"] == "keep"
    assert restored["bullet"]["tool"] == "claude"


def test_hub_ownership_boundary_uses_generation_as_identity():
    node = ownership_from_hub(
        "dt-a",
        {
            "state": "foreign",
            "holder": "tm_other",
            "instance_id": "remote:one",
            "generation": 8,
            "lease_protocol": 2,
            "renewed_at": 1_788_937_200,
            "expires_at": 1_788_937_204,
            "evidence": {"must": "not become a second fact source"},
        },
    )
    assert node.identity == "dt-a@8"
    assert node.renewed_at is not None
    assert not hasattr(node, "evidence")


def test_ownership_snapshot_boundary_preserves_unknown_probe():
    node = pane_from_ownership_facts(
        "dt-a",
        AgentRole.TRIGGER,
        "op_a",
        {
            "runtime": {"trigger": "down"},
            "attached": {"trigger": None},
            "progress": {"trigger": "unknown"},
            "writers": {
                "trigger": {
                    "status": "unknown",
                    "count": None,
                    "pids": [],
                    "reason": "probe_failed",
                }
            },
        },
        observed_at=NOW,
    )
    assert node.runtime.value == "down"
    assert node.writers.count is None


def test_existing_snapshot_revision_boundary_drops_process_path(tmp_path):
    from dual_tmux.oc import SnapshotRevision

    revision = SnapshotRevision(
        path=tmp_path / "session.json",
        session_id="ses_a",
        updated_ms=1_788_937_200_000,
        tail_id="msg_2",
        message_ids=frozenset({"msg_1", "msg_2"}),
        digest="a" * 64,
    )
    node = snapshot_from_revision(revision, source_tenant="andy")
    assert node.identity == f"ses_a@{'a' * 64}"
    assert node.tail_message_id == "msg_2"
    assert not hasattr(node, "path")
