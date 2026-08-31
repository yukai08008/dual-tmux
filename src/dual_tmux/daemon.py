"""Long-running dual-tmux service and supervised Feishu connector."""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import threading
import time
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

BACKOFF_SECONDS = (5, 15, 30, 60, 120)


def daemon_status_path() -> Path:
    return feishu_dir() / "daemon-status.json"


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
        self.lease_acquire = lease_acquire or self._claim_default_lease
        self.lease_release = lease_release or self._release_default_lease

    @staticmethod
    def _claim_default_lease() -> tuple[bool, str]:
        from .hub import claim_feishu_lease

        return claim_feishu_lease(load_config())

    @staticmethod
    def _release_default_lease() -> None:
        from .hub import release_feishu_lease

        release_feishu_lease(load_config())

    def owns_lease(self) -> bool:
        role = os.environ.get("DT_FEISHU_ROLE", "client").strip().lower()
        if role == "hub":
            self.owner = "hub"
            return True
        try:
            cfg = load_config()
            if cfg.hub_enabled:
                self.owner = cfg.server or "hub"
                return False
        except SystemExit:
            pass
        try:
            owned, holder = self.lease_acquire()
        except (SystemExit, OSError):
            owned, holder = False, "unavailable"
        self.owner = holder or "unknown"
        return owned

    @staticmethod
    def _new_process() -> ConnectorProcess:
        return multiprocessing.Process(
            target=run_feishu_connector,
            name="dt-feishu-ws",
            daemon=False,
        )

    def installed(self) -> bool:
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
            return {"connector": "stopped", "owner": "none", "failures": 0, "next_retry_at": 0}
        if not self.owns_lease():
            self.stop(release_lease=False)
            return {"connector": "standby", "owner": self.owner, "failures": 0, "next_retry_at": 0}
        if self.process and self.process.is_alive():
            return {"connector": "connected", "owner": self.owner, "failures": self.failures, "next_retry_at": 0}
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
                "failures": self.failures,
                "next_retry_at": int(self.next_start_at),
            }
        self.process = self.process_factory()
        self.process.start()
        return {"connector": "starting", "owner": self.owner, "failures": self.failures, "next_retry_at": 0}

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
        _atomic_json(
            daemon_status_path(),
            {
                **previous,
                "pid": os.getpid(),
                "running": True,
                "updated_at": int(time.time()),
                **connector,
            },
        )

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
            self.manager.stop()
            state = read_daemon_status()
            _atomic_json(
                daemon_status_path(),
                {**state, "running": False, "connector": "stopped", "updated_at": int(time.time())},
            )
            log.emit("dt.daemon.stop", pid=os.getpid())


def serve(*, once: bool = False) -> None:
    DualTmuxDaemon().run(once=once)
