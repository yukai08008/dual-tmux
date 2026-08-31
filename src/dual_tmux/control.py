"""Shared control contract for CLI, Web and future Feishu surfaces."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from . import tmux as tmux_ops
from .agents import capability_matrix, get_adapter
from .store import iter_dt_files, load


@dataclass(frozen=True)
class OperationSpec:
    name: str
    capability: str
    risk: str
    surfaces: tuple[str, ...]
    audit_event: str

    def as_dict(self) -> dict:
        data = asdict(self)
        data["surfaces"] = list(self.surfaces)
        return data


_OPERATIONS = (
    OperationSpec("tunnel.list", "detect", "read", ("cli", "web", "feishu"), "control.tunnel.list"),
    OperationSpec("tunnel.get", "detect", "read", ("cli", "web", "feishu"), "control.tunnel.get"),
    OperationSpec("pane.send", "send", "write", ("cli", "web", "feishu"), "control.pane.send"),
    OperationSpec("session.freeze", "metadata_freeze", "write", ("cli", "web", "feishu"), "control.session.freeze"),
    OperationSpec("session.resume", "resume", "execute", ("cli", "web", "feishu"), "control.session.resume"),
    OperationSpec("agent.model", "model", "execute", ("cli", "web", "feishu"), "control.agent.model"),
)


def operation_catalog() -> list[dict]:
    return [operation.as_dict() for operation in _OPERATIONS]


@dataclass
class ControlResult:
    operation: str
    data: Any = None
    audit_event: str = ""
    warnings: list[str] = field(default_factory=list)
    ok: bool = True

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "data": self.data,
            "audit_event": self.audit_event,
            "warnings": self.warnings,
        }


class ControlError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int = 400, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail or {}

    def as_dict(self) -> dict:
        return {
            "ok": False,
            "error": {"code": self.code, "message": str(self), "detail": self.detail},
        }


def _event(operation: str) -> str:
    return next(item.audit_event for item in _OPERATIONS if item.name == operation)


def _translate(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except ControlError:
        raise
    except SystemExit as exc:
        message = str(exc) or "operation failed"
        status = 404 if "unknown tunnel" in message or "no tunnels" in message else 409
        raise ControlError("operation_failed", message, status=status) from exc


class ControlService:
    """Stable application boundary shared by user-facing control surfaces."""

    def capabilities(self) -> ControlResult:
        return ControlResult("agent.capabilities", capability_matrix(), "control.agent.capabilities")

    def operations(self) -> ControlResult:
        return ControlResult("control.operations", operation_catalog(), "control.operations.list")

    def list_tunnels(self) -> ControlResult:
        rows = [load(path) for path in iter_dt_files()]
        return ControlResult("tunnel.list", rows, _event("tunnel.list"))

    def get_tunnel(self, name: str | None) -> ControlResult:
        # Reuse the established resolver so optional "latest" lookup and an
        # on-demand Hub pull retain their pre-control-kernel behavior.
        from .cli import _resolve

        data = _translate(lambda: _resolve(name))
        return ControlResult("tunnel.get", data, _event("tunnel.get"))

    def send(self, name: str, text: str, side: str = "bullet") -> ControlResult:
        data = self.get_tunnel(name).data
        normalized = {"op": "trigger", "run": "bullet"}.get(side, side)
        if normalized not in {"trigger", "bullet"}:
            raise ControlError("invalid_side", f"unsupported side: {side}")
        pane = data.get("op" if normalized == "trigger" else "run") or ""
        if not pane:
            raise ControlError("missing_pane", f"tunnel has no {normalized} pane", status=409)
        agent = (data.get(normalized) or {}).get("tool") or "opencode"
        self._require_capability(agent, "send")
        _translate(lambda: tmux_ops.send_keys(pane, text))
        return ControlResult("pane.send", {"pane": pane, "side": normalized}, _event("pane.send"))

    def freeze(self, name: str, sides: list[str] | None = None, tool: str = "auto") -> ControlResult:
        from .cli import _apply_freeze_legacy

        data = _translate(lambda: _apply_freeze_legacy(name, sides, tool))
        return ControlResult("session.freeze", data, _event("session.freeze"))

    def resume(self, name: str | None, force: bool = False) -> ControlResult:
        from .cli import _apply_resume_legacy

        # The legacy implementation validates both sides and preserves its exact safety checks.
        data = _translate(lambda: _apply_resume_legacy(name, force))
        return ControlResult("session.resume", data, _event("session.resume"))

    def model(self, name: str, model: str, sides: list[str]) -> ControlResult:
        data = self.get_tunnel(name).data
        target_sides = sides or ["bullet"]
        for side in target_sides:
            agent = (data.get(side) or {}).get("tool") or "opencode"
            self._require_capability(agent, "model")
        from .cli import _apply_model_legacy

        updated = _translate(lambda: _apply_model_legacy(name, model, sides))
        return ControlResult("agent.model", updated, _event("agent.model"))

    @staticmethod
    def _require_capability(agent: str, capability: str) -> None:
        adapter = get_adapter(agent)
        if adapter is None or not adapter.supports(capability):
            raise ControlError(
                "capability_not_supported",
                f"{agent or 'unknown'} does not support {capability}",
                status=409,
                detail={"agent": agent, "capability": capability},
            )


_DEFAULT_SERVICE = ControlService()


def get_control_service() -> ControlService:
    return _DEFAULT_SERVICE
