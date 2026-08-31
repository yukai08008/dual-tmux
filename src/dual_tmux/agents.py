"""Agent client adapters and truthful capability discovery.

The registry is deliberately declarative in v0.4.40.  It describes what dual-tmux
can safely do today, so every control surface can reject unsupported operations
before it attempts client-specific commands.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .agentclient import normalize_name


@dataclass(frozen=True)
class AgentCapabilities:
    detect: bool = True
    version: bool = True
    start: bool = False
    send: bool = True
    metadata_freeze: bool = True
    session_freeze: bool = False
    resume: bool = False
    model: bool = False
    local: bool = True
    ssh: bool = True
    docker: bool = True

    def supports(self, capability: str) -> bool:
        if not hasattr(self, capability):
            return False
        return bool(getattr(self, capability))

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class AgentAdapter:
    name: str
    display_name: str
    aliases: tuple[str, ...]
    capabilities: AgentCapabilities

    def supports(self, capability: str) -> bool:
        return self.capabilities.supports(capability)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "aliases": list(self.aliases),
            "capabilities": self.capabilities.as_dict(),
        }


_FULL_OPENCODE = AgentCapabilities(
    start=True,
    session_freeze=True,
    resume=True,
    model=True,
)

_ADAPTERS = {
    "opencode": AgentAdapter("opencode", "OpenCode", ("opencode",), _FULL_OPENCODE),
    "codex": AgentAdapter("codex", "Codex", ("codex", "codex-cli"), AgentCapabilities()),
    "claude": AgentAdapter(
        "claude",
        "Claude Code",
        ("claude", "claude-code"),
        AgentCapabilities(),
    ),
}


def get_adapter(name: str) -> AgentAdapter | None:
    """Return an adapter for a canonical name or supported executable alias."""
    return _ADAPTERS.get(normalize_name(name))


def require_adapter(name: str) -> AgentAdapter:
    adapter = get_adapter(name)
    if adapter is None:
        raise ValueError(f"unsupported agent client: {name or 'unknown'}")
    return adapter


def list_adapters() -> tuple[AgentAdapter, ...]:
    return tuple(_ADAPTERS[name] for name in ("opencode", "codex", "claude"))


def capability_matrix() -> list[dict]:
    """JSON-safe capability inventory for CLI, Web and future control planes."""
    return [adapter.as_dict() for adapter in list_adapters()]
