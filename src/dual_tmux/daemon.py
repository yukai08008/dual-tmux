"""Long-running dual-tmux service and supervised Feishu connector."""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Protocol

from . import log
from .config import load_config
from .feishu import (
    CredentialVault,
    FeishuDispatcher,
    FeishuError,
    OperatorIdentity,
    _atomic_json,
    feishu_dir,
)
from .paths import home_dir

BACKOFF_SECONDS = (5, 15, 30, 60, 120)


class LocalConnectorLease:
    """Process-held flock with a monotonic generation for one shared dt home."""

    def __init__(self, path: Path | None = None):
        self.path = path or (home_dir() / "locks" / "__feishu_ws__")
        self.handle = None
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self.generation = 0

    def claim(self) -> tuple[bool, str, int]:
        import fcntl

        if self.handle is not None:
            self.handle.seek(0)
            self.handle.truncate()
            self.handle.write(f"{self.owner}@{int(time.time())}@{self.generation}\n")
            self.handle.flush()
            return True, self.owner, self.generation
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = self.path.open("a+", encoding="utf-8")
        os.chmod(self.path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            text = handle.read()
            parts = text.strip().split("@")
            handle.close()
            return (
                False,
                parts[0] if parts else "another-daemon",
                int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
            )
        handle.seek(0)
        parts = handle.read().strip().split("@")
        previous = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        self.generation = previous + 1
        handle.seek(0)
        handle.truncate()
        handle.write(f"{self.owner}@{int(time.time())}@{self.generation}\n")
        handle.flush()
        os.fsync(handle.fileno())
        self.handle = handle
        return True, self.owner, self.generation

    def release(self) -> None:
        if self.handle is None:
            return
        self.handle.close()
        self.handle = None


def daemon_status_path() -> Path:
    return feishu_dir() / "daemon-status.json"


def daemon_instances_dir() -> Path:
    return feishu_dir() / "daemon-instances"


def _instance_status_path(owner: str) -> Path:
    import hashlib

    name = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:24]
    return daemon_instances_dir() / f"{name}.json"


def read_daemon_status() -> dict:
    path = daemon_status_path()
    if not path.is_file():
        return {"running": False, "connector": "stopped", "owner": "none"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"running": False, "connector": "unknown", "owner": "none"}
    pid = int(data.get("pid") or 0)
    try:
        if pid:
            os.kill(pid, 0)
    except OSError:
        data["running"] = False
    candidates = []
    now = time.time()
    root = daemon_instances_dir()
    for item in sorted(root.glob("*.json")) if root.is_dir() else []:
        try:
            candidate = json.loads(item.read_text(encoding="utf-8"))
            if now - float(candidate.get("updated_at") or 0) <= 30:
                candidates.append(
                    {
                        key: candidate.get(key)
                        for key in (
                            "instance",
                            "owner",
                            "connector",
                            "generation",
                            "updated_at",
                        )
                    }
                )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    data["candidates"] = candidates
    return data


class ConnectorProcess(Protocol):
    @property
    def exitcode(self) -> int | None: ...
    def is_alive(self) -> bool: ...
    def start(self) -> None: ...
    def terminate(self) -> None: ...
    def join(self, timeout: float | None = None) -> None: ...


def _reply_text(api_client, chat_id: str, text: str) -> None:
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        .build()
    )
    response = api_client.im.v1.message.create(request)
    if not response.success():
        raise FeishuError("reply_failed", f"Feishu reply failed: {response.code} {response.msg}")


def _result_text(result: dict) -> str:
    if result.get("confirmation_required"):
        return (
            f"需要确认：/dt {result.get('action')} {result.get('name')} "
            f"{result.get('token')}（{result.get('expires_in')} 秒内有效）"
        )
    payload = result.get("result") if result.get("ok") else result
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:12000]


def run_feishu_connector() -> None:
    """Child-process entrypoint; the parent daemon supervises this blocking SDK."""
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

    installation = CredentialVault().load()
    if not installation or not installation.get("active", True):
        raise FeishuError("not_installed", "no active Feishu installation")
    app_id = str(installation["app_id"])
    app_secret = str(installation["app_secret"])
    role = os.environ.get("DT_FEISHU_ROLE", "client").strip().lower()
    dispatcher = FeishuDispatcher()
    api_client = (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )

    def on_message(data: P2ImMessageReceiveV1) -> None:
        event = data.event
        message = event.message
        sender_id = event.sender.sender_id
        identity = OperatorIdentity(
            open_id=str(getattr(sender_id, "open_id", "") or ""),
            union_id=str(getattr(sender_id, "union_id", "") or ""),
            user_id=str(getattr(sender_id, "user_id", "") or ""),
        )
        event_id = str(getattr(data.header, "event_id", "") or message.message_id or "")
        try:
            content = json.loads(message.content or "{}")
            text = str(content.get("text") or "")
            for mention in message.mentions or []:
                key = str(getattr(mention, "key", "") or "")
                if key:
                    text = text.replace(key, "")
            if role == "hub":
                from .feishu_bridge import BridgeStore

                store = BridgeStore()
                client_name = store.client_for(identity)
                store.enqueue(
                    client_name,
                    "commands",
                    event_id,
                    {
                        "event_id": event_id,
                        "message_id": str(message.message_id),
                        "chat_id": str(message.chat_id),
                        "identity": identity.public_dict(),
                        "text": text.strip(),
                    },
                )
                reply = "指令已送达，等待对应 Client 执行。"
            else:
                result = dispatcher.dispatch(event_id, identity, text.strip())
                reply = _result_text(result)
        except FeishuError as exc:
            reply = f"请求未执行：{exc}"
        except Exception as exc:  # noqa: BLE001 - SDK callback must not crash silently.
            log.emit("feishu.ws.message.error", reason=type(exc).__name__)
            reply = "请求处理失败，请稍后重试。"
        _reply_text(api_client, str(message.chat_id), reply)
        state = read_daemon_status()
        state["last_message_at"] = int(time.time())
        _atomic_json(daemon_status_path(), state)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.WARNING,
        auto_reconnect=False,
    )
    if role == "hub":

        def flush_responses() -> None:
            from .feishu_bridge import BridgeStore, _read_envelope

            root = BridgeStore().root / "responses"
            while True:
                paths = sorted(root.glob("*/*.json")) if root.is_dir() else []
                for path in paths:
                    try:
                        item = _read_envelope(path)
                        chat_id = str(item.get("chat_id") or "")
                        if chat_id:
                            _reply_text(api_client, chat_id, str(item.get("text") or ""))
                            path.unlink(missing_ok=True)
                    except Exception as exc:  # noqa: BLE001 - keep the outbox worker alive.
                        log.emit("feishu.ws.response.error", reason=type(exc).__name__)
                time.sleep(2)

        threading.Thread(
            target=flush_responses, daemon=True, name="dt-feishu-outbox"
        ).start()
    client.start()


class ConnectorManager:
    def __init__(
        self,
        *,
        process_factory=None,
        clock=time.time,
        sleeper=time.sleep,
        lease_acquire=None,
        lease_release=None,
    ):
        self.process_factory = process_factory or self._new_process
        self.clock = clock
        self.sleeper = sleeper
        self.process: ConnectorProcess | None = None
        self.failures = 0
        self.next_start_at = 0.0
        self.owner = "none"
        self.generation = 0
        self.has_lease = False
        self.lease_owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self.local_lease = LocalConnectorLease()
        self.local_lease.owner = self.lease_owner
        self.lease_acquire = lease_acquire or self._claim_default_lease
        self.lease_release = lease_release or self._release_default_lease

    def _claim_default_lease(self) -> tuple[bool, str, int]:
        from .hub import claim_feishu_lease

        role = os.environ.get("DT_FEISHU_ROLE", "client").strip().lower()
        cfg = load_config()
        topology = os.environ.get("DT_FEISHU_TOPOLOGY", "").strip().lower()
        if role == "hub" or not cfg.hub_enabled:
            return self.local_lease.claim()
        if topology == "client-failover":
            return claim_feishu_lease(cfg, owner=self.lease_owner)
        return False, cfg.server or "hub", 0

    def _release_default_lease(self) -> None:
        from .hub import release_feishu_lease

        role = os.environ.get("DT_FEISHU_ROLE", "client").strip().lower()
        cfg = load_config()
        topology = os.environ.get("DT_FEISHU_TOPOLOGY", "").strip().lower()
        if role == "hub" or not cfg.hub_enabled:
            self.local_lease.release()
        elif topology == "client-failover":
            release_feishu_lease(cfg, owner=self.lease_owner)

    def owns_lease(self) -> bool:
        try:
            cfg = load_config()
            topology = os.environ.get("DT_FEISHU_TOPOLOGY", "").strip().lower()
            role = os.environ.get("DT_FEISHU_ROLE", "client").strip().lower()
            if cfg.hub_enabled and role != "hub" and topology != "client-failover":
                self.owner = cfg.server or "hub"
                self.generation = 0
                self.has_lease = False
                return False
        except SystemExit:
            pass
        try:
            lease = self.lease_acquire()
            owned, holder = lease[:2]
            generation = lease[2] if len(lease) > 2 else 0
        except (SystemExit, OSError):
            owned, holder, generation = False, "unavailable", 0
        self.owner = holder or "unknown"
        self.generation = int(generation or 0)
        self.has_lease = bool(owned)
        return owned

    @staticmethod
    def _new_process() -> ConnectorProcess:
        return multiprocessing.Process(
            target=run_feishu_connector,
            name="dt-feishu-ws",
            daemon=False,
        )

    def installed(self) -> bool:
        role = os.environ.get("DT_FEISHU_ROLE", "client").strip().lower()
        topology = os.environ.get("DT_FEISHU_TOPOLOGY", "").strip().lower()
        if role != "hub" and topology == "client-failover":
            try:
                cfg = load_config()
                if not cfg.hub_enabled:
                    return False
                from .feishu_bridge import sync_installation_from_hub

                if not sync_installation_from_hub(cfg):
                    return False
            except (FeishuError, SystemExit, OSError):
                return False
        try:
            item = CredentialVault().load()
        except FeishuError:
            return False
        return bool(item and item.get("active", True))

    def step(self) -> dict:
        now = self.clock()
        installed = self.installed()
        if not installed:
            self.stop()
            return {"connector": "stopped", "owner": "none", "generation": 0, "failures": 0, "next_retry_at": 0}
        if not self.owns_lease():
            self.stop(release_lease=False)
            return {"connector": "standby", "owner": self.owner, "generation": self.generation, "failures": 0, "next_retry_at": 0}
        if self.process and self.process.is_alive():
            return {"connector": "connected", "owner": self.owner, "generation": self.generation, "failures": self.failures, "next_retry_at": 0}
        if self.process is not None:
            self.process.join(timeout=0)
            self.process = None
            self.failures += 1
            delay = BACKOFF_SECONDS[min(self.failures - 1, len(BACKOFF_SECONDS) - 1)]
            self.next_start_at = now + delay
        if now < self.next_start_at:
            return {
                "connector": "backoff",
                "owner": self.owner,
                "generation": self.generation,
                "failures": self.failures,
                "next_retry_at": int(self.next_start_at),
            }
        self.process = self.process_factory()
        self.process.start()
        return {"connector": "starting", "owner": self.owner, "generation": self.generation, "failures": self.failures, "next_retry_at": 0}

    def stop(self, *, release_lease: bool = True) -> None:
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)
        self.process = None
        self.failures = 0
        self.next_start_at = 0
        if release_lease:
            try:
                self.lease_release()
            except (SystemExit, OSError):
                pass


class DualTmuxDaemon:
    def __init__(self, *, manager: ConnectorManager | None = None, interval: float = 2.0):
        self.manager = manager or ConnectorManager()
        self.interval = interval
        self.stop_event = threading.Event()

    def _write_status(self, connector: dict) -> None:
        previous = read_daemon_status()
        candidates = previous.pop("candidates", [])
        state = {
            **previous,
            "pid": os.getpid(),
            "instance": self.manager.lease_owner,
            "running": True,
            "updated_at": int(time.time()),
            **connector,
        }
        _atomic_json(_instance_status_path(self.manager.lease_owner), state)
        if connector.get("connector") != "standby":
            _atomic_json(daemon_status_path(), {**state, "candidates": candidates})

    def run(self, *, once: bool = False) -> None:
        def stop(_signum=None, _frame=None):
            self.stop_event.set()

        if not once:
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
        log.emit("dt.daemon.start", pid=os.getpid())
        try:
            while not self.stop_event.is_set():
                self._write_status(self.manager.step())
                if once:
                    return
                self.stop_event.wait(self.interval)
        finally:
            global_state = read_daemon_status()
            was_owner = self.manager.has_lease or int(global_state.get("pid") or 0) == os.getpid()
            instance_path = _instance_status_path(self.manager.lease_owner)
            self.manager.stop()
            instance_path.unlink(missing_ok=True)
            if was_owner:
                state = read_daemon_status()
                state.pop("candidates", None)
                _atomic_json(
                    daemon_status_path(),
                    {
                        **state,
                        "running": False,
                        "connector": "stopped",
                        "updated_at": int(time.time()),
                    },
                )
            log.emit("dt.daemon.stop", pid=os.getpid())


def serve(*, once: bool = False) -> None:
    DualTmuxDaemon().run(once=once)
