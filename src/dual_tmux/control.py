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
    OperationSpec(
        "tunnel.list", "detect", "read", ("cli", "web", "feishu"), "control.tunnel.list"
    ),
    OperationSpec(
        "tunnel.get", "detect", "read", ("cli", "web", "feishu"), "control.tunnel.get"
    ),
    OperationSpec(
        "pane.send", "send", "write", ("cli", "web", "feishu"), "control.pane.send"
    ),
    OperationSpec(
        "session.freeze",
        "metadata_freeze",
        "write",
        ("cli", "web", "feishu"),
        "control.session.freeze",
    ),
    OperationSpec(
        "session.resume",
        "resume",
        "execute",
        ("cli", "web", "feishu"),
        "control.session.resume",
    ),
    OperationSpec(
        "agent.model",
        "model",
        "execute",
        ("cli", "web", "feishu"),
        "control.agent.model",
    ),
    OperationSpec(
        "tunnel.create",
        "detect",
        "write",
        ("cli", "web", "feishu"),
        "control.tunnel.create",
    ),
    OperationSpec(
        "tunnel.remove",
        "detect",
        "destructive",
        ("cli", "web", "feishu"),
        "control.tunnel.remove",
    ),
    OperationSpec(
        "tunnel.reconnect",
        "detect",
        "execute",
        ("cli", "web", "feishu"),
        "control.tunnel.reconnect",
    ),
    OperationSpec(
        "tunnel.drop",
        "detect",
        "execute",
        ("cli", "web", "feishu"),
        "control.tunnel.drop",
    ),
    OperationSpec(
        "hub.push",
        "detect",
        "network-write",
        ("cli", "web", "feishu"),
        "control.hub.push",
    ),
    OperationSpec(
        "hub.pull",
        "detect",
        "network-write",
        ("cli", "web", "feishu"),
        "control.hub.pull",
    ),
    OperationSpec(
        "config.switch",
        "detect",
        "high-risk",
        ("cli", "web", "feishu"),
        "control.config.switch",
    ),
    OperationSpec(
        "health.probe",
        "detect",
        "network-read",
        ("cli", "web", "feishu"),
        "control.health.probe",
    ),
    OperationSpec(
        "health.recover",
        "resume",
        "execute",
        ("cli", "web", "feishu"),
        "control.health.recover",
    ),
    OperationSpec(
        "health.auto",
        "detect",
        "write",
        ("cli", "web", "feishu"),
        "control.health.auto",
    ),
    OperationSpec(
        "memory.get", "detect", "read", ("cli", "web", "feishu"), "control.memory.get"
    ),
    OperationSpec(
        "memory.fact",
        "detect",
        "write",
        ("cli", "web", "feishu"),
        "control.memory.fact",
    ),
    OperationSpec(
        "memory.note",
        "detect",
        "write",
        ("cli", "web", "feishu"),
        "control.memory.note",
    ),
    OperationSpec(
        "events.list", "detect", "read", ("cli", "web", "feishu"), "control.events.list"
    ),
    OperationSpec(
        "doctor.run",
        "detect",
        "network-read",
        ("cli", "web", "feishu"),
        "control.doctor.run",
    ),
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
    def __init__(
        self, code: str, message: str, *, status: int = 400, detail: dict | None = None
    ):
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
        return ControlResult(
            "agent.capabilities", capability_matrix(), "control.agent.capabilities"
        )

    def operations(self) -> ControlResult:
        return ControlResult(
            "control.operations", operation_catalog(), "control.operations.list"
        )

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
            raise ControlError(
                "missing_pane", f"tunnel has no {normalized} pane", status=409
            )
        agent = (data.get(normalized) or {}).get("tool") or "opencode"
        self._require_capability(agent, "send")
        _translate(lambda: tmux_ops.send_keys(pane, text))
        return ControlResult(
            "pane.send", {"pane": pane, "side": normalized}, _event("pane.send")
        )

    def freeze(
        self, name: str, sides: list[str] | None = None, tool: str = "auto"
    ) -> ControlResult:
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

    def create_tunnel(
        self,
        name: str,
        *,
        server: str = "",
        container: str = "",
        directory: str = "",
        trigger_tool: str = "opencode",
        bullet_tool: str = "opencode",
        local: bool = False,
    ) -> ControlResult:
        import argparse

        from .cli import cmd_new
        from .store import find_dt

        clean = (name or "").strip()
        if not clean:
            raise ControlError("invalid_name", "tunnel name is required")
        tools = {}
        for side, tool in (("trigger", trigger_tool), ("bullet", bullet_tool)):
            adapter = get_adapter(tool)
            if adapter is None or not adapter.supports("start"):
                raise ControlError(
                    "capability_not_supported",
                    f"{tool or 'unknown'} cannot start a native session",
                    status=409,
                )
            tools[side] = adapter.name
        _translate(
            lambda: cmd_new(
                argparse.Namespace(
                    name=clean,
                    op=None,
                    run=None,
                    server=(server or "").strip(),
                    container=(container or "").strip(),
                    dir=(directory or "").strip(),
                    cmd="",
                    local=bool(local),
                )
            )
        )
        data = load(find_dt(clean))
        for side, tool in tools.items():
            data.setdefault(side, {})["tool"] = tool
        from . import hub
        from .store import save

        save(find_dt(clean), data)
        hub.push_best_effort(wait=True)
        return ControlResult("tunnel.create", data, _event("tunnel.create"))

    def remove_tunnel(
        self, name: str, *, confirm: str, kill: bool = False
    ) -> ControlResult:
        import argparse

        data = self.get_tunnel(name).data
        expected = data.get("name") or ""
        if confirm != expected:
            raise ControlError(
                "confirmation_required",
                f"confirmation must exactly match {expected}",
                status=409,
            )
        from .cli import cmd_rm

        _translate(
            lambda: cmd_rm(argparse.Namespace(name=expected, yes=True, kill=kill))
        )
        return ControlResult(
            "tunnel.remove",
            {"name": expected, "kill": bool(kill)},
            _event("tunnel.remove"),
        )

    def reconnect(self, name: str) -> ControlResult:
        data = self.get_tunnel(name).data
        command = (data.get("runtime") or {}).get("cmd") or ""
        if not command:
            raise ControlError(
                "missing_runtime", "tunnel has no runtime.cmd", status=409
            )
        _translate(lambda: tmux_ops.reconnect(data.get("run") or "", command))
        return ControlResult("tunnel.reconnect", data, _event("tunnel.reconnect"))

    def drop(self, name: str, *, confirm: str = "") -> ControlResult:
        from . import hub

        data = self.get_tunnel(name).data
        if confirm != data.get("name"):
            raise ControlError(
                "confirmation_required",
                "drop requires the exact tunnel name",
                status=409,
            )
        dropped = _translate(lambda: hub.drop_local(data))
        try:
            hub.release(data.get("name") or "")
        except SystemExit:
            pass
        return ControlResult(
            "tunnel.drop",
            {"name": data.get("name"), "dropped": dropped},
            _event("tunnel.drop"),
        )

    def hub_sync(self, direction: str) -> ControlResult:
        from . import hub

        if direction not in {"push", "pull"}:
            raise ControlError("invalid_direction", "direction must be push or pull")
        value = _translate(hub.push if direction == "push" else hub.pull)
        operation = f"hub.{direction}"
        return ControlResult(operation, {"destination": value}, _event(operation))

    def switch_mode(
        self,
        *,
        mode: str,
        client: str,
        workspace: str,
        server: str = "",
        user: str = "",
        confirm: str = "",
    ) -> ControlResult:
        from .config import load_config, make_config, switch_config

        if confirm != "switch-mode":
            raise ControlError(
                "confirmation_required",
                "mode switch requires confirm=switch-mode",
                status=409,
            )
        mode = (mode or "").strip().lower()
        if mode not in {"local", "hub"}:
            raise ControlError("invalid_mode", "mode must be local or hub")
        candidate = _translate(
            lambda: make_config(
                client,
                server if mode == "hub" else "",
                user if mode == "hub" else "",
                workspace,
            )
        )
        current = load_config()
        path = _translate(lambda: switch_config(current, candidate))
        return ControlResult(
            "config.switch",
            {
                "mode": candidate.mode,
                "client": candidate.client,
                "server": candidate.server,
                "user": candidate.user,
                "workspace": candidate.workspace,
                "path": str(path),
            },
            _event("config.switch"),
        )

    def probe_health(self, name: str) -> ControlResult:
        from . import recovery

        data = self.get_tunnel(name).data
        state = _translate(lambda: recovery.observe(data, auto=False))
        return ControlResult("health.probe", state, _event("health.probe"))

    def recover(
        self, name: str, *, force: bool = False, confirm: str = ""
    ) -> ControlResult:
        from . import recovery

        data = self.get_tunnel(name).data
        if force and confirm != data.get("name"):
            raise ControlError(
                "confirmation_required",
                "force recovery requires the exact tunnel name",
                status=409,
            )
        state = _translate(lambda: recovery.recover_now(data, force=force))
        return ControlResult("health.recover", state, _event("health.recover"))

    def set_auto_recover(self, name: str, enabled: bool) -> ControlResult:
        from . import recovery

        data = _translate(lambda: recovery.set_enabled(name, bool(enabled)))
        return ControlResult("health.auto", data, _event("health.auto"))

    def memory(self, name: str = "") -> ControlResult:
        from . import memory

        data = {
            "memory": memory.peek_memory(name or None),
            "notes": memory.peek_notes(name) if name else [],
        }
        return ControlResult("memory.get", data, _event("memory.get"))

    def put_memory_fact(self, key: str, value: Any, name: str = "") -> ControlResult:
        from . import memory

        data = _translate(lambda: memory.put_fact(key, value, name or None))
        return ControlResult("memory.fact", data, _event("memory.fact"))

    def add_memory_note(self, name: str, body: str, title: str = "") -> ControlResult:
        from . import memory

        data = _translate(lambda: memory.add_note(name, body, title=title))
        return ControlResult("memory.note", data, _event("memory.note"))

    def events(
        self, *, limit: int = 100, kind: str = "", name: str = ""
    ) -> ControlResult:
        from . import log

        rows = log.read_events(limit=min(500, max(1, limit)), kind=kind, name=name)
        return ControlResult("events.list", rows, _event("events.list"))

    def doctor(self) -> ControlResult:
        from dataclasses import asdict

        from .health import collect_checks

        _cfg, checks = collect_checks()
        data = {
            "ok": all(check.ok for check in checks if check.required),
            "checks": [asdict(check) for check in checks],
        }
        return ControlResult("doctor.run", data, _event("doctor.run"))

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
