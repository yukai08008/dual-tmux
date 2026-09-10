"""Compatibility boundary between legacy tunnel dictionaries and DataNodes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .models import (
    AgentClientMetadata,
    AgentRole,
    AgentSessionNode,
    DockerEndpointNode,
    LeaseState,
    LocalEndpointNode,
    OccupancyNode,
    OwnershipLeaseNode,
    PaneRuntimeNode,
    RoleBindingNode,
    RuntimeEndpointNode,
    SnapshotRevisionNode,
    SshEndpointNode,
    TunnelNode,
    WriterEvidence,
    WriterStatus,
)


class RevisionLike(Protocol):
    session_id: str
    updated_ms: int
    tail_id: str
    message_ids: frozenset[str]
    digest: str
    path: Path


def _datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _session(raw: object) -> AgentSessionNode | None:
    value = raw if isinstance(raw, dict) else {}
    session_id = str(value.get("session_id") or "").strip()
    if not session_id:
        return None
    client_raw = value.get("agent_client")
    client = None
    if isinstance(client_raw, dict) and any(client_raw.values()):
        client = AgentClientMetadata(
            name=str(client_raw.get("name") or ""),
            version=str(client_raw.get("version") or ""),
            version_output=str(client_raw.get("version_output") or ""),
            executable=str(client_raw.get("executable") or ""),
            location=str(client_raw.get("location") or ""),
            host=str(client_raw.get("host") or ""),
            container=str(client_raw.get("container") or ""),
            collected_at=_datetime(client_raw.get("collected_at")),
            error=str(client_raw.get("error") or ""),
        )
    return AgentSessionNode(
        session_id=session_id,
        tool=str(value.get("tool") or "opencode"),
        model=str(value.get("model") or ""),
        slug=str(value.get("slug") or ""),
        agent=str(value.get("agent") or ""),
        directory=str(value.get("directory") or ""),
        client=client,
    )


def _binding(
    raw: object, role: AgentRole, tunnel_name: str
) -> RoleBindingNode | None:
    session = _session(raw)
    if session is None:
        return None
    value = raw if isinstance(raw, dict) else {}
    return RoleBindingNode(
        tunnel_name=tunnel_name,
        role=role,
        session=session,
        parser=str(value.get("parser") or ""),
        frozen_at=_datetime(value.get("frozen_at")),
        bound_by_client=str(value.get("bound_by_client") or ""),
    )


def _endpoint(raw: object) -> RuntimeEndpointNode:
    value = raw if isinstance(raw, dict) else {}
    server = str(value.get("server") or "")
    container = str(value.get("container") or "")
    directory = str(value.get("directory") or "")
    port = int(value.get("ssh_port") or 22)
    if container:
        return DockerEndpointNode(
            server=server, container=container, directory=directory, port=port
        )
    if server:
        return SshEndpointNode(server=server, directory=directory, port=port)
    return LocalEndpointNode(directory=directory)


def from_legacy_tunnel(record: dict[str, Any]) -> TunnelNode:
    """Validate one current tunnel JSON record as an in-memory domain node."""
    return TunnelNode(
        name=str(record.get("name") or ""),
        op=str(record.get("op") or ""),
        run=str(record.get("run") or ""),
        endpoint=_endpoint(record.get("runtime")),
        trigger=_binding(record.get("trigger"), AgentRole.TRIGGER, str(record.get("name") or "")),
        bullet=_binding(record.get("bullet"), AgentRole.BULLET, str(record.get("name") or "")),
        client=str(record.get("client") or ""),
        user=str(record.get("user") or ""),
        branched_from=(
            str(record["branched_from"]) if record.get("branched_from") else None
        ),
        updated_at=_datetime(record.get("updated_at")),
    )


def _side(node: RoleBindingNode | None, base: object) -> dict[str, Any]:
    value = deepcopy(base) if isinstance(base, dict) else {}
    if node is None:
        return value
    session = node.session
    value.update(
        tool=session.tool,
        parser=node.parser,
        model=session.model,
        session_id=session.session_id,
        slug=session.slug,
        agent=session.agent,
        directory=session.directory,
        frozen_at=node.frozen_at.isoformat() if node.frozen_at else "",
    )
    if node.bound_by_client:
        value["bound_by_client"] = node.bound_by_client
    if session.client is not None:
        client = session.client.model_dump(mode="json", exclude_none=True)
        client["collected_at"] = client.get("collected_at") or ""
        value["agent_client"] = client
    return value


def to_legacy_tunnel(
    node: TunnelNode, *, base: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Project a node back to JSON while preserving unrelated legacy fields."""
    record = deepcopy(base) if base is not None else {}
    endpoint = node.endpoint
    runtime = deepcopy(record.get("runtime") or {})
    runtime.update(
        server=getattr(endpoint, "server", ""),
        ssh_port=getattr(endpoint, "port", 22),
        container=getattr(endpoint, "container", ""),
        directory=endpoint.directory,
        cmd=endpoint.reconnect_command,
    )
    record.update(
        name=node.name,
        op=node.op,
        run=node.run,
        client=node.client,
        user=node.user,
        runtime=runtime,
        trigger=_side(node.trigger, record.get("trigger")),
        bullet=_side(node.bullet, record.get("bullet")),
        updated_at=node.updated_at.isoformat() if node.updated_at else "",
    )
    if node.branched_from:
        record["branched_from"] = node.branched_from
    else:
        record.pop("branched_from", None)
    return record


def _epoch(value: object) -> datetime | None:
    try:
        stamp = int(value or 0)
    except (TypeError, ValueError):
        stamp = 0
    return datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp else None


def occupancy_from_hub(payload: dict[str, Any]) -> OccupancyNode:
    """Convert occupancy JSON without copying lock or leftover lease sidecars."""
    name = str(payload.get("name") or payload.get("tunnel_name") or "")
    return OccupancyNode(
        tunnel_name=name,
        holder=str(payload.get("holder") or ""),
        generation=int(payload.get("generation") or 0),
        claimed_at=_epoch(payload.get("claimed_at")),
    )


def ownership_from_hub(tunnel_name: str, lease: dict[str, Any]) -> OwnershipLeaseNode:
    """Convert leftover lease dicts for tests. OccupancyNode is the exclusive-control fact."""
    return OwnershipLeaseNode(
        tunnel_name=tunnel_name,
        generation=int(lease.get("generation") or 0),
        state=LeaseState(str(lease.get("state") or "free")),
        holder=str(lease.get("holder") or ""),
        instance_id=str(lease.get("instance_id") or ""),
        protocol=int(lease.get("lease_protocol") or 1),
        renewed_at=_epoch(lease.get("renewed_at")),
        expires_at=_epoch(lease.get("expires_at")),
    )


def pane_from_ownership_facts(
    tunnel_name: str,
    role: AgentRole,
    tmux_session: str,
    facts: dict[str, Any],
    *,
    observed_at: datetime,
) -> PaneRuntimeNode:
    """Convert one role from `ownership.snapshot()` into an observation node."""
    role_name = role.value
    raw_writers = (facts.get("writers") or {}).get(role_name) or {}
    status = WriterStatus(str(raw_writers.get("status") or "unknown"))
    raw_count = raw_writers.get("count")
    return PaneRuntimeNode(
        tunnel_name=tunnel_name,
        role=role,
        observed_at=observed_at,
        tmux_session=tmux_session,
        runtime=str((facts.get("runtime") or {}).get(role_name) or "unknown"),
        attached=(facts.get("attached") or {}).get(role_name),
        progress=str((facts.get("progress") or {}).get(role_name) or "unknown"),
        writers=WriterEvidence(
            status=status,
            count=None if status is WriterStatus.UNKNOWN else int(raw_count or 0),
            pids=tuple(int(pid) for pid in raw_writers.get("pids") or ()),
            reason=str(raw_writers.get("reason") or ""),
        ),
    )


def snapshot_from_revision(
    revision: RevisionLike, *, source_tenant: str = ""
) -> SnapshotRevisionNode:
    """Convert the existing OpenCode revision value without retaining its Path."""
    return SnapshotRevisionNode(
        session_id=revision.session_id,
        digest=revision.digest,
        updated_at=datetime.fromtimestamp(revision.updated_ms / 1000, tz=timezone.utc),
        message_ids=revision.message_ids,
        tail_message_id=revision.tail_id,
        source_tenant=source_tenant,
    )
