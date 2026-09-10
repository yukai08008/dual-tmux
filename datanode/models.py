"""Pydantic definitions for dual-tmux business and runtime nodes.

These models contain no I/O. Adapters convert to and from current JSON dicts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class NodeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentRole(str, Enum):
    TRIGGER = "trigger"
    BULLET = "bullet"


class LeaseState(str, Enum):
    FREE = "free"
    EXPIRED = "expired"
    OWNED = "owned"
    FOREIGN = "foreign"


class RuntimeKind(str, Enum):
    DOWN = "down"
    SHELL = "shell"
    TRANSPORT = "transport"
    AGENT = "agent"
    UNKNOWN = "unknown"


class WriterStatus(str, Enum):
    OK = "ok"
    DUPLICATE = "duplicate"
    UNKNOWN = "unknown"


class BindingIntent(str, Enum):
    FREEZE = "freeze"
    REBUILD = "rebuild"


class BindingAttemptState(str, Enum):
    CREATED = "created"
    PROVING = "proving"
    COMMITTING = "committing"
    BOUND = "bound"
    REJECTED = "rejected"
    FAILED = "failed"


class AgentClientMetadata(NodeModel):
    """Observed Agent executable metadata; absence never invalidates a binding."""

    name: str = ""
    version: str = ""
    version_output: str = ""
    executable: str = ""
    location: Literal["", "local", "ssh", "docker"] = ""
    host: str = ""
    container: str = ""
    collected_at: datetime | None = None
    error: str = ""


class AgentSessionNode(NodeModel):
    """Native recoverable Agent session. Role is not an attribute of the session."""

    session_id: str = Field(min_length=1)
    tool: str = Field(default="opencode", min_length=1)
    model: str = ""
    slug: str = ""
    agent: str = ""
    directory: str = ""
    client: AgentClientMetadata | None = None

    @computed_field
    @property
    def identity(self) -> str:
        return f"{self.tool}:{self.session_id}"


class RoleBindingNode(NodeModel):
    """A tunnel role bound to one Agent session. This is the DST relation."""

    tunnel_name: str = Field(pattern=r"^dt-")
    role: AgentRole
    session: AgentSessionNode
    parser: str = ""
    frozen_at: datetime | None = None
    bound_by_client: str = ""

    @computed_field
    @property
    def identity(self) -> str:
        return f"{self.tunnel_name}:{self.role.value}"


class ClientNode(NodeModel):
    """User-visible machine identity (tm_*). Occupancy holder is this id."""

    client_id: str = Field(pattern=r"^tm_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    user: str = ""
    display_name: str = ""


class LocalEndpointNode(NodeModel):
    kind: Literal["local"] = "local"
    directory: str = ""

    @computed_field
    @property
    def identity(self) -> str:
        return f"local:{self.directory}"

    @computed_field
    @property
    def reconnect_command(self) -> str:
        if not self.directory:
            return ""
        from dual_tmux.runtime import build_cmd

        return build_cmd("", "", self.directory)


class SshEndpointNode(NodeModel):
    kind: Literal["ssh"] = "ssh"
    server: str = Field(min_length=1)
    port: int = Field(default=22, ge=1, le=65535)
    directory: str = "/workspace"

    @computed_field
    @property
    def identity(self) -> str:
        return f"ssh:{self.server}:{self.port}:{self.directory}"

    @computed_field
    @property
    def reconnect_command(self) -> str:
        from dual_tmux.runtime import build_cmd

        return build_cmd(self.server, "", self.directory, self.port)


class DockerEndpointNode(NodeModel):
    kind: Literal["docker"] = "docker"
    server: str = Field(min_length=1)
    container: str = Field(min_length=1)
    directory: str = Field(min_length=1)
    port: int = Field(default=22, ge=1, le=65535)

    @computed_field
    @property
    def identity(self) -> str:
        return f"docker:{self.server}:{self.port}:{self.container}:{self.directory}"

    @computed_field
    @property
    def reconnect_command(self) -> str:
        from dual_tmux.runtime import build_cmd

        return build_cmd(self.server, self.container, self.directory, self.port)


RuntimeEndpointNode = Annotated[
    LocalEndpointNode | SshEndpointNode | DockerEndpointNode,
    Field(discriminator="kind"),
]


class TunnelNode(NodeModel):
    """User-visible dual-ended tunnel. DST means both role bindings exist."""

    name: str = Field(pattern=r"^dt-[A-Za-z0-9][A-Za-z0-9_.-]*$")
    op: str = Field(pattern=r"^op_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    run: str = Field(pattern=r"^run_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    endpoint: RuntimeEndpointNode
    trigger: RoleBindingNode | None = None
    bullet: RoleBindingNode | None = None
    client: str = ""
    user: str = ""
    branched_from: str | None = None
    updated_at: datetime | None = None

    @computed_field
    @property
    def is_dst(self) -> bool:
        return self.trigger is not None and self.bullet is not None

    @model_validator(mode="after")
    def legal_bindings(self) -> TunnelNode:
        if self.op == self.run:
            raise ValueError("op and run tmux identities must differ")
        for binding, expected in (
            (self.trigger, AgentRole.TRIGGER),
            (self.bullet, AgentRole.BULLET),
        ):
            if binding is None:
                continue
            if binding.role is not expected:
                raise ValueError(f"{expected.value} binding must have role={expected.value}")
            if binding.tunnel_name != self.name:
                raise ValueError("binding tunnel_name must match TunnelNode.name")
        if (
            self.trigger
            and self.bullet
            and self.trigger.session.session_id == self.bullet.session.session_id
        ):
            raise ValueError("trigger and bullet cannot bind the same session")
        return self


class OccupancyNode(NodeModel):
    """Hub occupancy: last resume writer owns the trigger. No TTL."""

    tunnel_name: str = Field(pattern=r"^dt-")
    holder: str = ""
    generation: int = Field(ge=0)
    claimed_at: datetime | None = None

    @computed_field
    @property
    def identity(self) -> str:
        return f"{self.tunnel_name}@{self.generation}"

    def is_foreign(self, client: str) -> bool:
        return bool(self.holder and self.holder != client)


class BindingAttemptNode(NodeModel):
    """One freeze or rebuild attempt. Graph/Machine is not wired until states are confirmed."""

    attempt_id: str = Field(min_length=1)
    tunnel_name: str = Field(pattern=r"^dt-")
    role: AgentRole
    intent: BindingIntent
    state: BindingAttemptState = BindingAttemptState.CREATED
    holder: str = ""
    previous_session_id: str = ""
    candidate_session_id: str = ""
    candidate_directory: str = ""
    error: str = ""

    @computed_field
    @property
    def identity(self) -> str:
        return self.attempt_id

    @model_validator(mode="after")
    def legal_candidate(self) -> BindingAttemptNode:
        if self.state in {BindingAttemptState.COMMITTING, BindingAttemptState.BOUND}:
            if not self.candidate_session_id:
                raise ValueError("committing/bound attempts require a proven session")
            if (
                self.previous_session_id
                and self.previous_session_id == self.candidate_session_id
                and self.intent is BindingIntent.REBUILD
            ):
                raise ValueError("rebuild must bind a different session than the previous one")
        return self


class OwnershipLeaseNode(NodeModel):
    """Legacy lease snapshot. OccupancyNode is the exclusive-control fact."""

    tunnel_name: str = Field(pattern=r"^dt-")
    generation: int = Field(ge=0)
    state: LeaseState
    holder: str = ""
    instance_id: str = ""
    protocol: int = Field(default=1, ge=1)
    renewed_at: datetime | None = None
    expires_at: datetime | None = None

    @computed_field
    @property
    def identity(self) -> str:
        return f"{self.tunnel_name}@{self.generation}"

    @model_validator(mode="after")
    def legal_owner(self) -> OwnershipLeaseNode:
        if self.state in {LeaseState.OWNED, LeaseState.FOREIGN} and not self.holder:
            raise ValueError("an active lease requires a holder")
        if (
            self.state in {LeaseState.OWNED, LeaseState.FOREIGN}
            and self.protocol >= 2
            and not self.instance_id
        ):
            raise ValueError("an active v2 lease requires an instance_id")
        return self

    def succeeds(self, previous: OwnershipLeaseNode) -> bool:
        if self.tunnel_name != previous.tunnel_name:
            raise ValueError("cannot compare generations from different tunnels")
        return self.generation >= previous.generation


class WriterEvidence(NodeModel):
    status: WriterStatus
    count: int | None = Field(default=None, ge=0)
    pids: tuple[int, ...] = ()
    reason: str = ""

    @model_validator(mode="after")
    def legal_count(self) -> WriterEvidence:
        if self.status is WriterStatus.UNKNOWN:
            if self.count is not None:
                raise ValueError("unknown writer evidence must not claim a count")
        elif self.count is None or self.count != len(self.pids):
            raise ValueError("writer count must equal the number of PIDs")
        if self.status is WriterStatus.DUPLICATE and (self.count or 0) < 2:
            raise ValueError("duplicate writer evidence requires at least two PIDs")
        return self


class PaneRuntimeNode(NodeModel):
    """Ephemeral observation of one role's tmux pane, never a binding source."""

    tunnel_name: str = Field(pattern=r"^dt-")
    role: AgentRole
    observed_at: datetime
    tmux_session: str = Field(min_length=1)
    runtime: RuntimeKind
    attached: bool | None = None
    progress: str = "unknown"
    writers: WriterEvidence

    @computed_field
    @property
    def identity(self) -> str:
        return f"{self.tunnel_name}:{self.role}:{self.observed_at.isoformat()}"


class SnapshotRevisionNode(NodeModel):
    """Content identity used to select/reject a recoverable session snapshot."""

    session_id: str = Field(min_length=1)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    updated_at: datetime
    message_ids: frozenset[str] = frozenset()
    tail_message_id: str = ""
    source_tenant: str = ""

    @computed_field
    @property
    def identity(self) -> str:
        return f"{self.session_id}@{self.digest}"

    @model_validator(mode="after")
    def legal_tail(self) -> SnapshotRevisionNode:
        if self.tail_message_id and self.tail_message_id not in self.message_ids:
            raise ValueError("snapshot tail must be present in message_ids")
        return self
