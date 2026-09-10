"""Non-authoritative Resume FSM observer.

The observer mirrors facts already produced by the legacy resume flow.  It
does not perform probes, ownership operations, tmux actions, or snapshot I/O.
Any observer failure is reduced to a diagnostic event and must never alter the
user-visible operation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from datanode.runtime_fsm import ResumeAttemptNode, ResumeEvent, ResumeMachine

from . import log as event_log
from .config import load_config
from .hub import existing_instance_id
from .paths import home_dir

F = TypeVar("F")


def _non_blocking(method: F) -> F:
    """Keep all observer preparation failures outside the real resume path."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self._emit_violation(self.name, self.attempt_id, method.__name__, exc)
            return None

    return wrapped  # type: ignore[return-value]


class AtomicShadowStateStore:
    """Atomic local snapshots for non-authoritative, per-attempt shadow state."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or home_dir() / "fsm-shadow" / "resume"

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.base_dir / f"{digest}.json"

    def save(self, key: str, data: dict[str, Any]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(prefix="resume.", suffix=".tmp", dir=self.base_dir)
        temporary = Path(raw)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path(key))
        finally:
            temporary.unlink(missing_ok=True)

    def load(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_keys(self) -> list[str]:
        if not self.base_dir.is_dir():
            return []
        keys = []
        for path in self.base_dir.glob("*.json"):
            try:
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                attempt_id = str((snapshot.get("node") or {}).get("attempt_id") or "")
            except (AttributeError, OSError, json.JSONDecodeError):
                continue
            if attempt_id:
                keys.append(f"resume:{attempt_id}")
        return sorted(keys)

    def prune(self, keep: int = 200) -> None:
        """Bound diagnostic disk usage without touching current resume data."""
        if not self.base_dir.is_dir():
            return
        paths = sorted(
            self.base_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in paths[max(0, keep) :]:
            path.unlink(missing_ok=True)


class ResumeShadow:
    """Best-effort adapter from the legacy resume path to ``ResumeMachine``."""

    def __init__(
        self,
        machine: ResumeMachine | None,
        *,
        name: str,
        attempt_id: str,
        claimant_client_id: str = "",
        claimant_instance_id: str = "",
    ):
        self.machine = machine
        self.name = name
        self.attempt_id = attempt_id
        self.claimant_client_id = claimant_client_id
        self.claimant_instance_id = claimant_instance_id

    @classmethod
    def start(cls, tunnel: dict) -> ResumeShadow:
        name = str(tunnel.get("name") or "")
        attempt_id = f"resume-{uuid.uuid4().hex}"
        try:
            config = load_config()
            installation_id = existing_instance_id() or f"local:{config.client}"
            node = ResumeAttemptNode(
                attempt_id=attempt_id,
                idempotency_key=attempt_id,
                tunnel_name=name,
                claimant_client_id=config.client,
                claimant_instance_id=installation_id,
            )
            store = AtomicShadowStateStore()
            observer = cls(
                ResumeMachine.create(node, store),
                name=name,
                attempt_id=attempt_id,
                claimant_client_id=config.client,
                claimant_instance_id=installation_id,
            )
            store.prune()
            observer._send(ResumeEvent.PROCESSING_STARTED, {})
            return observer
        # A diagnostic observer is never allowed to fail the real operation.
        except Exception as exc:  # noqa: BLE001
            cls._emit_violation(name, attempt_id, "start", exc)
            return cls(None, name=name, attempt_id=attempt_id)

    @_non_blocking
    def preflight(self, tunnel: dict, plan: dict) -> None:
        if not plan.get("safe"):
            self._send(
                ResumeEvent.PREFLIGHT_REJECTED,
                {
                    "error": self._error(
                        "preflight_rejected", plan.get("reason"), "preflight"
                    )
                },
            )
            return
        revisions = tuple(
            f"{role}:{self._digest(tunnel.get(role) or {})}"
            for role in ("trigger", "bullet")
        )
        self._send(
            ResumeEvent.PREFLIGHT_PASSED,
            {"binding_revisions": revisions, "revisions_stable": True},
        )

    @_non_blocking
    def preflight_failed(self, exc: BaseException) -> None:
        self._send(
            ResumeEvent.PREFLIGHT_REJECTED,
            {"error": self._error("preflight_failed", exc, "preflight")},
        )

    @_non_blocking
    def ownership_acquired(self, token: dict) -> None:
        generation = int(token.get("generation") or 0)
        self._send(
            ResumeEvent.OWNERSHIP_ACQUIRED,
            {
                "token": {
                    "tunnel_name": self.name,
                    "holder_client_id": self.claimant_client_id,
                    "holder_instance_id": self.claimant_instance_id,
                    "generation": generation,
                    "lease_revision": f"generation:{generation}",
                    "newly_acquired": bool(token.get("newly_acquired")),
                }
            },
        )

    @_non_blocking
    def ownership_failed(self, exc: BaseException) -> None:
        self._send(
            ResumeEvent.OWNERSHIP_FAILED,
            {"error": self._error("ownership_failed", exc, "ownership")},
        )

    @_non_blocking
    def restore_completed(self) -> None:
        self._send(ResumeEvent.RESTORE_COMPLETED, {"transfer_ids": []})

    @_non_blocking
    def restore_failed(self, exc: BaseException) -> None:
        self._send(
            ResumeEvent.RESTORE_FAILED,
            {"error": self._error("restore_failed", exc, "restore")},
        )

    @_non_blocking
    def verification_passed(self, verified: dict) -> None:
        writers = verified.get("writers") or {}
        generation = int(verified.get("generation") or 0)
        self._send(
            ResumeEvent.VERIFICATION_PASSED,
            {
                "evidence": {
                    "generation": generation,
                    "trigger_writer_count": int(
                        (writers.get("trigger") or {}).get("count") or 0
                    ),
                    "bullet_writer_count": int(
                        (writers.get("bullet") or {}).get("count") or 0
                    ),
                    "trigger_observation_id": self._digest(
                        {"generation": generation, "writer": writers.get("trigger")}
                    ),
                    "bullet_observation_id": self._digest(
                        {"generation": generation, "writer": writers.get("bullet")}
                    ),
                }
            },
        )

    @_non_blocking
    def verification_failed(self, exc: BaseException) -> None:
        self._send(
            ResumeEvent.VERIFICATION_FAILED,
            {"error": self._error("verification_failed", exc, "verification")},
        )

    @_non_blocking
    def rollback_completed(self, *, parked: bool, lease_released: bool) -> None:
        evidence = []
        if parked:
            evidence.append("attempt_resources_parked")
        if lease_released:
            evidence.append("new_lease_released")
        self._send(
            ResumeEvent.ROLLBACK_COMPLETED,
            {
                "evidence": evidence,
                "panes_parked": parked,
                "lease_released": lease_released,
            },
        )

    @_non_blocking
    def rollback_uncertain(self, exc: BaseException | str) -> None:
        self._send(
            ResumeEvent.ROLLBACK_UNCERTAIN,
            {"error": self._error("rollback_uncertain", exc, "rollback")},
        )

    def _send(self, event: ResumeEvent, payload: dict) -> None:
        if self.machine is None:
            return
        try:
            state = self.machine.send(event, payload)
            event_log.emit(
                "fsm.shadow.resume.transition",
                name=self.name,
                attempt_id=self.attempt_id,
                transition_event=event.value,
                state=state.value,
            )
        # A diagnostic observer is never allowed to fail the real operation.
        except Exception as exc:  # noqa: BLE001
            self._emit_violation(self.name, self.attempt_id, event.value, exc)

    @staticmethod
    def _digest(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _error(code: str, value: Any, stage: str) -> dict:
        return {"code": code, "message": str(value or code), "stage": stage}

    @staticmethod
    def _emit_violation(name: str, attempt_id: str, stage: str, exc: Exception) -> None:
        try:
            event_log.emit(
                "fsm.shadow.resume.violation",
                name=name,
                attempt_id=attempt_id,
                stage=stage,
                error=f"{type(exc).__name__}: {exc}",
            )
        # There is no lower-level sink left; preserve the real resume result.
        except Exception:  # noqa: BLE001, S110
            pass


__all__ = ["AtomicShadowStateStore", "ResumeShadow"]
