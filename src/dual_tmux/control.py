"""Shared control contract for CLI, Web and future Feishu surfaces."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import ValidationError

from datanode.fsm_core import TransitionError

from . import tmux as tmux_ops
from .agents import capability_matrix, get_adapter
from .store import load


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
        "pane.interrupt",
        "send",
        "write",
        ("cli", "web", "feishu"),
        "control.pane.interrupt",
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
        "session.resume.plan",
        "resume",
        "read",
        ("cli", "web", "feishu"),
        "control.session.resume.plan",
    ),
    OperationSpec(
        "ownership.get",
        "detect",
        "read",
        ("cli", "web", "feishu"),
        "control.ownership.get",
    ),
    OperationSpec(
        "ownership.handoff",
        "resume",
        "write",
        ("cli", "web", "feishu"),
        "control.ownership.handoff",
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
    except (TransitionError, ValidationError) as exc:
        raise ControlError("fsm_rejected", str(exc), status=409) from exc


class ControlService:
    """Stable application boundary shared by user-facing control surfaces."""

    def __init__(self, repository: Any | None = None) -> None:
        from datanode import TunnelRepository

        self.repository = repository or TunnelRepository()

    def capabilities(self) -> ControlResult:
        return ControlResult(
            "agent.capabilities", capability_matrix(), "control.agent.capabilities"
        )

    def operations(self) -> ControlResult:
        return ControlResult(
            "control.operations", operation_catalog(), "control.operations.list"
        )

    def list_tunnels(self) -> ControlResult:
        rows = [load(path) for path in self.repository.list_paths()]
        return ControlResult("tunnel.list", rows, _event("tunnel.list"))

    def list_tunnel_nodes(self) -> list[Any]:
        """Return strongly-typed TunnelNode list from repository."""
        return self.repository.list()

    def get_tunnel_node(self, name: str | None) -> Any:
        """Get strongly-typed TunnelNode by name (or latest)."""
        from datanode import from_legacy_tunnel

        data = self.get_tunnel(name).data
        return from_legacy_tunnel(data)

    def save_tunnel_node(self, node: Any) -> None:
        """Save TunnelNode through repository."""
        self.repository.save(node)

    def get_tunnel(self, name: str | None) -> ControlResult:
        # Reuse the established resolver so optional "latest" lookup and an
        # on-demand Hub pull retain their pre-control-kernel behavior.
        from .cli import _resolve

        data = _translate(lambda: _resolve(name))
        return ControlResult("tunnel.get", data, _event("tunnel.get"))

    def get_tunnel_readonly(self, name: str | None) -> ControlResult:
        """Return a local binding without Hub synchronization side effects."""
        data = _translate(lambda: self._get_tunnel_readonly(name))
        return ControlResult("tunnel.get", data, _event("tunnel.get"))

    def _get_tunnel_readonly(self, name: str | None) -> dict:
        """Resolve only the local binding; never pull or create directories."""
        if name:
            try:
                return self.repository.get_raw(name)
            except KeyError as exc:
                raise SystemExit(f"[err] unknown tunnel: {name}") from exc
        from .store import latest_dt

        return load(latest_dt())

    def send(self, name: str, text: str, side: str = "bullet") -> ControlResult:
        from . import hub

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
        _translate(lambda: hub.require_active(data))
        _translate(lambda: tmux_ops.send_keys(pane, text))
        return ControlResult(
            "pane.send", {"pane": pane, "side": normalized}, _event("pane.send")
        )

    def interrupt(
        self, name: str, side: str = "bullet", kind: str = "ctrl_c"
    ) -> ControlResult:
        from . import hub

        data = self.get_tunnel(name).data
        normalized = {"op": "trigger", "run": "bullet"}.get(side, side)
        if normalized not in {"trigger", "bullet"}:
            raise ControlError("invalid_side", f"unsupported side: {side}")
        pane = data.get("op" if normalized == "trigger" else "run") or ""
        if not pane:
            raise ControlError(
                "missing_pane", f"tunnel has no {normalized} pane", status=409
            )
        _translate(lambda: hub.require_active(data))
        key = "Escape" if str(kind).strip().lower() in {"esc", "escape"} else "C-c"
        _translate(lambda: tmux_ops.send_interrupt(pane, key))
        return ControlResult(
            "pane.interrupt",
            {"pane": pane, "side": normalized, "kind": key},
            _event("pane.interrupt"),
        )

    def freeze(
        self, name: str, sides: list[str] | None = None, tool: str = "auto"
    ) -> ControlResult:
        from pydantic import ValidationError

        from datanode.adapters import from_legacy_tunnel

        from .cli import _apply_freeze_legacy

        data = _translate(lambda: _apply_freeze_legacy(name, sides, tool))
        try:
            from_legacy_tunnel(data)
        except (ValidationError, ValueError) as exc:
            raise ControlError(
                "invalid_tunnel_node",
                f"freeze committed an invalid TunnelNode: {exc}",
                status=409,
            ) from exc
        return ControlResult("session.freeze", data, _event("session.freeze"))

    def resume(self, name: str | None, force: bool = False) -> ControlResult:
        from . import hub, ownership, recovery
        from . import log as ev
        from . import oc as oc_ops
        from .cli import (
            _apply_resume_legacy,
            _preflight_resume_snapshots,
            refresh_resume_inputs,
            write_entry,
        )
        from .resume_attempt import ResumeAttempt
        from .store import find_dt, save

        def note(action) -> None:
            try:
                action()
            except (TransitionError, ValidationError, ValueError, OSError):
                pass

        try:
            original = _translate(lambda: self._get_tunnel_readonly(name))
        except ControlError:
            from .cli import _resolve

            original = _translate(lambda: _resolve(name))
        # Pull DST + persist/ticks, then preflight. Occupancy is claimed only
        # after the winning machine's data is already local and preflight_passed.
        original = _translate(lambda: refresh_resume_inputs(original))
        attempt = _translate(lambda: ResumeAttempt.start(original))
        try:
            remote_opencode = bool((original.get("runtime") or {}).get("server")) and (
                ((original.get("bullet") or {}).get("tool") or "opencode") == "opencode"
            )
            route = (
                _translate(lambda: recovery.reconcile_remote_runtime(original))
                if remote_opencode
                else {"status": "not-applicable", "changed": False, "locations": []}
            )
            if route["status"] == "ambiguous":
                names = ", ".join(item["location"] for item in route["locations"])
                raise ControlError(
                    "runtime_ambiguous",
                    f"[err] bullet session exists in multiple remote locations ({names}); runtime was not changed",
                    status=409,
                )
            if (
                remote_opencode
                and route["status"] == "missing"
                and oc_ops.persist_snapshot(original.get("bullet") or {}) is None
            ):
                sid = (original.get("bullet") or {}).get("session_id") or ""
                raise ControlError(
                    "session_missing",
                    f"[err] bullet session {sid} missing remotely and no local persist JSON",
                    status=409,
                )
            if route["changed"]:
                _translate(
                    lambda: save(find_dt(str(original.get("name") or "")), original)
                )
                _translate(
                    lambda: write_entry(
                        str(original.get("run") or ""),
                        str((original.get("runtime") or {}).get("cmd") or ""),
                    )
                )
                hub.sync_best_effort()
            _translate(lambda: _preflight_resume_snapshots(original))
            plan = _translate(lambda: ownership.plan_resume(original))
        except BaseException as exc:
            note(lambda err=exc: attempt.preflight_failed(err))
            raise
        _translate(lambda: attempt.preflight(original, plan))
        try:
            token = _translate(
                lambda: ownership.acquire_for_resume(original, plan, force=force)
            )
        except BaseException as exc:
            if plan.get("safe"):
                note(lambda err=exc: attempt.ownership_failed(err))
            raise
        _translate(lambda: attempt.ownership_acquired(token))
        restore_completed = False
        rollback_started = False
        try:
            data = _translate(
                lambda: _apply_resume_legacy(
                    name,
                    force,
                    ownership_checked=True,
                    finalize=False,
                    native_generation=int(token.get("generation") or 0),
                )
            )
            _translate(lambda: attempt.restore_completed())
            restore_completed = True
            try:
                verified = _translate(lambda: ownership.verify_resume(data, token))
            except BaseException as exc:
                note(lambda err=exc: attempt.verification_failed(err))
                rollback_started = True
                raise
            data["ownership_generation"] = verified["generation"]
            save(find_dt(str(data.get("name") or "")), data)
            ev.emit(
                "dt.resume", name=data.get("name"), generation=verified["generation"]
            )
            _translate(lambda: attempt.verification_passed(verified))
        except BaseException as exc:
            if not restore_completed:
                note(lambda err=exc: attempt.restore_failed(err))
            elif not rollback_started:
                note(lambda err=exc: attempt.verification_failed(err))
            # Occupancy is already claimed. Do not park local tmux: a failed
            # resume must not kick the operator out.
            note(lambda: attempt.keep_occupancy_after_failure())
            raise
        hub.push_best_effort()
        return ControlResult("session.resume", data, _event("session.resume"))

    def ownership(self, name: str | None) -> ControlResult:
        from . import ownership

        data = _translate(lambda: self._get_tunnel_readonly(name))
        facts = _translate(lambda: ownership.snapshot(data))
        return ControlResult("ownership.get", facts, _event("ownership.get"))

    def plan_resume(self, name: str | None) -> ControlResult:
        from . import ownership

        data = _translate(lambda: self._get_tunnel_readonly(name))
        plan = _translate(lambda: ownership.plan_resume(data))
        return ControlResult("session.resume.plan", plan, _event("session.resume.plan"))

    def cached_ownership(self, name: str | None) -> ControlResult:
        """Web-safe ownership facts; never probes tmux, processes, SSH or Hub."""
        from . import ownership

        data = _translate(lambda: self._get_tunnel_readonly(name))
        cached = ownership.read_cache(str(data.get("name") or ""))
        return ControlResult("ownership.get", cached, _event("ownership.get"))

    def cached_resume_plan(self, name: str | None) -> ControlResult:
        """Web equivalent of ``dt resume --plan`` using cached evidence."""
        from . import ownership

        data = _translate(lambda: self._get_tunnel_readonly(name))
        cached = ownership.read_cache(str(data.get("name") or ""))
        if not cached.get("available"):
            plan = {
                "schema": ownership.SCHEMA,
                "name": str(data.get("name") or ""),
                "safe": False,
                "action": "stop",
                "reason": "ownership_cache_missing",
                "steps": [],
                "ownership": None,
            }
        else:
            plan = ownership.plan_from_facts(data, cached["facts"])
            if cached.get("freshness") != "fresh":
                plan.update(
                    safe=False, action="stop", reason="ownership_cache_stale", steps=[]
                )
            else:
                facts = cached["facts"]
                lease = facts.get("lease") or {}
                sampled = int((lease.get("evidence") or {}).get("sampled_at") or 0)
                if lease.get("state") == "foreign" and (
                    not sampled or int(time.time()) - sampled > ownership.EVIDENCE_TTL
                ):
                    plan.update(
                        safe=True,
                        action="claim",
                        reason="occupancy_steal",
                        steps=["claim", "prepare", "restore", "verify"],
                    )
        plan["cache"] = {
            key: cached.get(key) for key in ("cached_at", "age_seconds", "freshness")
        }
        return ControlResult("session.resume.plan", plan, _event("session.resume.plan"))

    def handoff(self, name: str, *, reason: str = "") -> ControlResult:
        """Occupancy steal uses the same pull-then-claim resume path."""
        from . import ownership

        data = _translate(lambda: self._get_tunnel_readonly(name))
        plan = _translate(lambda: ownership.plan_resume(data))
        if not plan.get("safe"):
            raise ControlError(
                "handoff_preflight_rejected",
                f"handoff preflight rejected: {plan.get('reason') or 'unsafe'}",
                status=409,
                detail={
                    "safe": bool(plan.get("safe")),
                    "action": plan.get("action") or "stop",
                    "reason": plan.get("reason") or "unsafe",
                },
            )
        return self.resume(name)

    def model(self, name: str, model: str, sides: list[str]) -> ControlResult:
        from pydantic import ValidationError

        from datanode.adapters import from_legacy_tunnel

        data = self.get_tunnel(name).data
        target_sides = sides or ["bullet"]
        for side in target_sides:
            agent = (data.get(side) or {}).get("tool") or "opencode"
            self._require_capability(agent, "model")
        from .cli import _apply_model_legacy

        updated = _translate(lambda: _apply_model_legacy(name, model, sides))
        try:
            from_legacy_tunnel(updated)
        except (ValidationError, ValueError) as exc:
            raise ControlError(
                "invalid_tunnel_node",
                f"model update committed an invalid TunnelNode: {exc}",
                status=409,
            ) from exc
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
        data = self.repository.get_raw(clean)
        for side, tool in tools.items():
            data.setdefault(side, {})["tool"] = tool
        from . import hub

        self.repository.save_raw(data)
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
