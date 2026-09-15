"""Versioned contracts for the current Web API and control result envelope.

The endpoint table is deliberately independent from the legacy HTTP handler.
Tests compare it with the live routes so framework migrations cannot silently
drop an endpoint.  It is a compatibility inventory, not a router.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WebEndpoint:
    method: str
    path: str
    risk: str
    response: str
    errors: str = "legacy-mixed"
    request: str = "query"
    operation: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "method": self.method,
            "path": self.path,
            "request": self.request,
            "response": self.response,
            "errors": self.errors,
            "risk": self.risk,
            "operation": self.operation,
        }


def _get(
    path: str,
    *,
    response: str = "raw-json",
    risk: str = "read",
    operation: str = "",
    errors: str = "legacy-mixed",
) -> WebEndpoint:
    return WebEndpoint("GET", path, risk, response, errors, "query", operation)


def _post(
    path: str,
    *,
    response: str = "control-result-v1",
    risk: str = "write",
    operation: str = "",
    request: str = "form",
    errors: str | None = None,
) -> WebEndpoint:
    error_shape = errors or ("control-error-v1" if operation else "legacy-mixed")
    return WebEndpoint("POST", path, risk, response, error_shape, request, operation)


# Keep this list explicit: each change is a public compatibility decision.
_ENDPOINTS = (
    _get("/api/capabilities", response="control-result-v1", operation="agent.capabilities"),
    _get("/api/config"),
    _get("/api/events", operation="events.list"),
    _get("/api/feishu/status", risk="network-read"),
    _get("/api/health"),
    _get("/api/memory", operation="memory.get"),
    _get("/api/models", risk="network-read"),
    _get("/api/operations", response="control-result-v1", operation="control.operations"),
    _get("/api/ownership", response="control-result-v1", operation="ownership.get"),
    _get("/api/resume/plan", response="control-result-v1", operation="session.resume.plan"),
    _get("/api/skill-body"),
    _get("/api/skill-file"),
    _get("/api/skill-installed-file"),
    _get("/api/skill-log"),
    _get("/api/skill-preview", risk="network-read"),
    _get("/api/skill-tree"),
    _get("/api/skills"),
    _get("/api/tunnel"),
    _get("/api/tunnels"),
    _get("/api/web-state"),
    _post("/api/config/switch", operation="config.switch", risk="high-risk"),
    _post(
        "/api/doctor/run",
        operation="doctor.run",
        risk="network-read",
        errors="legacy-mixed",
    ),
    _post("/api/feishu/pair", response="raw-json", request="json"),
    _post("/api/feishu/poll", response="raw-json", risk="network-read", request="json"),
    _post("/api/feishu/unbind", response="raw-json", request="json"),
    _post("/api/freeze", response="legacy-envelope", operation="session.freeze"),
    _post("/api/health/auto", operation="health.auto"),
    _post("/api/health/probe", operation="health.probe", risk="network-read"),
    _post("/api/health/recover", operation="health.recover", risk="execute"),
    _post("/api/interrupt", operation="pane.interrupt"),
    _post("/api/hub/pull", operation="hub.pull", risk="network-write"),
    _post("/api/hub/push", operation="hub.push", risk="network-write"),
    _post("/api/memory/fact", operation="memory.fact"),
    _post("/api/memory/note", operation="memory.note"),
    _post(
        "/api/model",
        response="legacy-envelope",
        operation="agent.model",
        risk="execute",
    ),
    _post("/api/ownership/handoff", operation="ownership.handoff"),
    _post(
        "/api/resume",
        response="legacy-envelope",
        operation="session.resume",
        risk="execute",
        errors="legacy-mixed",
    ),
    _post("/api/skill-enable", response="legacy-envelope"),
    _post("/api/skill-import", response="legacy-envelope", risk="network-write"),
    _post("/api/skill-teach", response="legacy-envelope"),
    _post("/api/skill-upload", response="legacy-envelope", request="multipart"),
    _post("/api/skill-used", response="legacy-envelope"),
    _post("/api/trigger-auto", response="legacy-envelope"),
    _post("/api/tunnel/create", operation="tunnel.create"),
    _post("/api/tunnel/drop", operation="tunnel.drop", risk="execute"),
    _post("/api/tunnel/reconnect", operation="tunnel.reconnect", risk="execute"),
    _post("/api/tunnel/remove", operation="tunnel.remove", risk="destructive"),
    _post("/api/web-state", response="raw-json", request="json"),
)


def web_api_manifest() -> dict[str, Any]:
    """Return the stable inventory of the legacy Web API surface."""
    return {
        "schema_version": SCHEMA_VERSION,
        "base_path": "/api",
        "endpoints": [
            endpoint.as_dict()
            for endpoint in sorted(_ENDPOINTS, key=lambda item: (item.path, item.method))
        ],
    }


def control_envelope_manifest() -> dict[str, Any]:
    """Describe the machine fields shared by CLI, Web, and Feishu adapters."""
    return {
        "schema_version": SCHEMA_VERSION,
        "success": {
            "required": ["ok", "operation", "data", "audit_event", "warnings"],
            "constants": {"ok": True},
        },
        "error": {
            "required": ["ok", "error"],
            "constants": {"ok": False},
            "error_required": ["code", "message", "detail"],
            "http_status_source": "ControlError.status",
        },
    }
