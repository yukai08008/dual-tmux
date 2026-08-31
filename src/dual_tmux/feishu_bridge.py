"""tom7r mailbox bridge for Feishu OAuth and command events.

The public bridge never reaches a Client directly.  It writes durable envelopes
under the Hub root; each Client pulls its own inbox over the already configured
SSH transport and executes commands locally through :mod:`dual_tmux.feishu`.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import log
from .config import AppConfig, load_config
from .feishu import (
    FeishuConfig,
    FeishuDispatcher,
    FeishuError,
    FeishuOAuthTransport,
    OperatorIdentity,
    PairingService,
    load_app_secret,
    load_feishu_config,
)
from .identity import legal_source
from .paths import home_dir

MAX_ENVELOPE = 256 * 1024
PAIR_TTL_SECONDS = 10 * 60


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bridge_root() -> Path:
    return home_dir() / "feishu" / "bridge"


def _write_envelope(path: Path, payload: dict) -> Path:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > MAX_ENVELOPE:
        raise FeishuError("envelope_too_large", "bridge envelope exceeds 256 KiB")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.parent / f".{path.name}.{secrets.token_hex(6)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        path.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def _read_envelope(path: Path) -> dict:
    if path.stat().st_size > MAX_ENVELOPE:
        raise FeishuError("envelope_too_large", f"oversized bridge envelope: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeishuError("invalid_envelope", f"invalid bridge envelope: {path.name}") from exc
    if not isinstance(value, dict):
        raise FeishuError("invalid_envelope", f"invalid bridge envelope: {path.name}")
    return value


def _safe_client(client: str) -> str:
    if not legal_source(client):
        raise FeishuError("invalid_client", "bridge Client must be a legal tm_* source")
    return client


class BridgeStore:
    """Filesystem mailbox used on tom7r and in deterministic integration tests."""

    def __init__(self, root: Path | None = None, clock=time.time):
        self.root = root or bridge_root()
        self.clock = clock

    def register_pairing(self, state: str, client: str, expires_at: float) -> Path:
        client = _safe_client(client)
        return _write_envelope(
            self.root / "pairing" / f"{_digest(state)}.json",
            {"client": client, "expires_at": expires_at},
        )

    def consume_pairing(self, state: str) -> str:
        source = self.root / "pairing" / f"{_digest(state)}.json"
        claimed = self.root / "consumed" / f"{_digest(state)}.json"
        claimed.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.replace(source, claimed)
        except OSError as exc:
            raise FeishuError("invalid_state", "pairing state is unknown or already used") from exc
        data = _read_envelope(claimed)
        if float(data.get("expires_at") or 0) <= self.clock():
            raise FeishuError("invalid_state", "pairing state has expired")
        return _safe_client(str(data.get("client") or ""))

    def register_routes(self, identity: OperatorIdentity, client: str) -> None:
        client = _safe_client(client)
        for identity_id in identity.ids():
            _write_envelope(
                self.root / "routes" / f"{_digest(identity_id)}.json",
                {"client": client, "updated_at": self.clock()},
            )

    def client_for(self, identity: OperatorIdentity) -> str:
        clients = set()
        for identity_id in identity.ids():
            path = self.root / "routes" / f"{_digest(identity_id)}.json"
            if path.is_file():
                clients.add(_safe_client(str(_read_envelope(path).get("client") or "")))
        if len(clients) != 1:
            raise FeishuError("route_missing", "operator is not paired to exactly one Client")
        return clients.pop()

    def enqueue(self, client: str, kind: str, envelope_id: str, payload: dict) -> Path:
        client = _safe_client(client)
        if kind not in {"callbacks", "commands", "responses"}:
            raise FeishuError("invalid_envelope", "unsupported bridge envelope kind")
        filename = f"{_digest(envelope_id)}.json"
        return _write_envelope(self.root / kind / client / filename, payload)


def begin_hub_pairing(config: FeishuConfig | None = None, cfg: AppConfig | None = None) -> dict:
    """Upload one pairing state to tom7r over SSH and return its Feishu URL."""
    from . import hub

    config = config or load_feishu_config()
    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        raise FeishuError("hub_required", "Feishu remote pairing requires Hub mode")
    started = PairingService().begin(config, ttl=PAIR_TTL_SECONDS)
    state = started["state"]
    expires_at = time.time() + PAIR_TTL_SECONDS
    with tempfile.TemporaryDirectory(prefix="dt-feishu-pair-") as raw:
        local = Path(raw) / f"{_digest(state)}.json"
        _write_envelope(local, {"client": _safe_client(cfg.client), "expires_at": expires_at})
        remote_dir = f"{hub.remote_root(cfg)}/feishu/bridge/pairing"
        result = hub._run(hub.ssh_argv(cfg) + [f"mkdir -p {remote_dir} && chmod 700 {remote_dir}"])
        if result.returncode != 0:
            raise FeishuError("bridge_unavailable", "cannot initialize Hub pairing mailbox")
        host = hub.SshTarget(cfg.server, cfg.ssh_port).dest
        try:
            hub._rsync(str(local), f"{host}:{remote_dir}/{local.name}", cfg)
        except SystemExit as exc:
            raise FeishuError("bridge_unavailable", str(exc)) from exc
    log.emit("feishu.bridge.pair", client=cfg.client, state=_digest(state)[:12])
    return {**started, "via": cfg.server}


def publish_installation_to_hub(
    cfg: AppConfig | None = None, identity: OperatorIdentity | None = None
) -> str:
    """Copy only encrypted credentials and hashed routes to the Hub."""
    from . import hub
    from .feishu import CredentialVault

    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        raise FeishuError("hub_required", "installation publishing requires Hub mode")
    vault = CredentialVault()
    if not vault.installation_path.is_file() or not vault.key_path.is_file():
        raise FeishuError("not_installed", "no encrypted Feishu installation to publish")
    remote = f"{hub.remote_root(cfg)}/feishu"
    host = hub.SshTarget(cfg.server, cfg.ssh_port).dest
    result = hub._run(
        hub.ssh_argv(cfg)
        + [f"mkdir -p {remote}/bridge/routes && chmod 700 {remote} {remote}/bridge"]
    )
    if result.returncode != 0:
        raise SystemExit("[err] cannot prepare Hub Feishu directory")
    hub._rsync(str(vault.key_path), f"{host}:{remote}/credential.key", cfg)
    hub._rsync(str(vault.installation_path), f"{host}:{remote}/installation.json", cfg)
    if identity and identity.ids():
        with tempfile.TemporaryDirectory(prefix="dt-feishu-routes-") as raw:
            store = BridgeStore(Path(raw) / "bridge")
            store.register_routes(identity, cfg.client)
            hub._rsync(
                f"{store.root / 'routes'}/", f"{host}:{remote}/bridge/routes/", cfg
            )
    log.emit("feishu.installation.hub", host=host, client=cfg.client)
    return f"{host}:{remote}"


def remove_installation_from_hub(cfg: AppConfig | None = None) -> None:
    """Stop the Hub connector by atomically removing its active installation."""
    from . import hub

    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        return
    remote = f"{hub.remote_root(cfg)}/feishu"
    result = hub._run(
        hub.ssh_argv(cfg)
        + [
            "rm",
            "-f",
            f"{remote}/installation.json",
            f"{remote}/credential.key",
        ]
    )
    if result.returncode != 0:
        raise FeishuError(
            "hub_unbind_failed",
            "Hub did not confirm credential removal; installation remains bound",
        )
    log.emit("feishu.installation.hub_remove", host=cfg.server)


def _format_result(payload: dict) -> str:
    if payload.get("confirmation_required"):
        return (
            f"需要二次确认：/dt {payload.get('action')} {payload.get('name')} "
            f"{payload.get('token')}（{payload.get('expires_in')} 秒内有效）"
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)[:12000]


def sync_client(cfg: AppConfig | None = None, dispatcher: FeishuDispatcher | None = None) -> dict:
    """Pull this Client's inbox, execute it once, and publish response envelopes."""
    from . import hub

    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        return {"ok": True, "mode": "local", "callbacks": 0, "commands": 0}
    client = _safe_client(cfg.client)
    dispatcher = dispatcher or FeishuDispatcher()
    host = hub.SshTarget(cfg.server, cfg.ssh_port).dest
    remote = f"{hub.remote_root(cfg)}/feishu/bridge"
    counts = {"callbacks": 0, "commands": 0, "errors": 0}
    with tempfile.TemporaryDirectory(prefix="dt-feishu-sync-") as raw:
        snapshot = Path(raw)
        for kind in ("callbacks", "commands"):
            local_dir = snapshot / kind
            local_dir.mkdir(parents=True)
            result = hub._run(
                hub.ssh_argv(cfg)
                + [f"mkdir -p {remote}/{kind}/{client} {remote}/responses/{client}"]
            )
            if result.returncode != 0:
                raise FeishuError("bridge_unavailable", "cannot open Hub Feishu mailbox")
            try:
                hub._rsync(f"{host}:{remote}/{kind}/{client}/", f"{local_dir}/", cfg)
            except SystemExit as exc:
                raise FeishuError("bridge_unavailable", str(exc)) from exc
            for path in sorted(local_dir.glob("*.json")):
                item = {}
                try:
                    item = _read_envelope(path)
                    if kind == "callbacks":
                        identity = OperatorIdentity.from_dict(item.get("identity") or {})
                        PairingService().complete_identity_digest(
                            str(item.get("state_digest") or ""), identity
                        )
                        result_payload = {"ok": True, "bound": identity.public_dict()}
                    else:
                        identity = OperatorIdentity.from_dict(item.get("identity") or {})
                        result_payload = dispatcher.dispatch(
                            str(item.get("event_id") or ""), identity, str(item.get("text") or "")
                        )
                    counts[kind] += 1
                except FeishuError as exc:
                    counts["errors"] += 1
                    result_payload = exc.as_dict()
                response = {
                    "event_id": str(item.get("event_id") or path.stem),
                    "message_id": str(item.get("message_id") or ""),
                    "chat_id": str(item.get("chat_id") or ""),
                    "text": _format_result(result_payload),
                    "payload": result_payload,
                }
                response_path = snapshot / f"response-{path.name}"
                _write_envelope(response_path, response)
                hub._rsync(response_path.as_posix(), f"{host}:{remote}/responses/{client}/{path.name}", cfg)
                removal = hub._run(hub.ssh_argv(cfg) + ["rm", "-f", f"{remote}/{kind}/{client}/{path.name}"])
                if removal.returncode != 0:
                    counts["errors"] += 1
    log.emit("feishu.bridge.sync", client=client, **counts)
    return {"ok": counts["errors"] == 0, "mode": "hub", **counts}


class FeishuReplyTransport:
    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"

    @staticmethod
    def _request(url: str, payload: dict, token: str = "") -> dict:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode())
        except Exception as exc:
            raise FeishuError("reply_transport", "Feishu reply request failed") from exc

    def reply(self, config: FeishuConfig, secret: str, message_id: str, text: str) -> None:
        auth = self._request(self.token_url, {"app_id": config.app_id, "app_secret": secret})
        token = str(auth.get("tenant_access_token") or "")
        if not token:
            raise FeishuError("reply_transport", "Feishu returned no tenant access token")
        result = self._request(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{urllib.parse.quote(message_id)}/reply",
            {"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
            token,
        )
        if result.get("code") not in (None, 0):
            raise FeishuError("reply_rejected", str(result.get("msg") or "reply rejected"))


class BridgeApplication:
    def __init__(
        self,
        store: BridgeStore | None = None,
        oauth: FeishuOAuthTransport | None = None,
        reply: FeishuReplyTransport | None = None,
        config: FeishuConfig | None = None,
    ):
        self.store = store or BridgeStore()
        self.oauth = oauth or FeishuOAuthTransport()
        self.reply_transport = reply or FeishuReplyTransport()
        self.config = config

    def app_config(self) -> FeishuConfig:
        return self.config or load_feishu_config()

    def callback(self, state: str, code: str) -> OperatorIdentity:
        client = self.store.consume_pairing(state)
        config = self.app_config()
        identity = self.oauth.exchange(config, load_app_secret(config), code)
        if not identity.ids():
            raise FeishuError("identity_missing", "Feishu returned no stable identity")
        if config.allowlist and not identity.ids().intersection(config.allowlist):
            raise FeishuError("operator_not_allowed", "operator is not in the allowlist")
        self.store.register_routes(identity, client)
        self.store.enqueue(
            client,
            "callbacks",
            f"callback:{state}",
            {
                "event_id": f"callback:{_digest(state)}",
                "state_digest": _digest(state),
                "identity": identity.public_dict(),
            },
        )
        log.emit("feishu.bridge.callback", client=client, operator=_digest("\0".join(sorted(identity.ids())))[:16])
        return identity

    def event(self, payload: dict) -> dict:
        expected = os.environ.get("DT_FEISHU_VERIFICATION_TOKEN", "")
        supplied = str(payload.get("token") or (payload.get("header") or {}).get("token") or "")
        if not expected:
            raise FeishuError("verification_missing", "DT_FEISHU_VERIFICATION_TOKEN is required")
        if not secrets.compare_digest(expected, supplied):
            raise FeishuError("verification_failed", "Feishu verification token rejected")
        if payload.get("type") == "url_verification":
            return {"challenge": str(payload.get("challenge") or "")}
        header = payload.get("header") or {}
        event = payload.get("event") or {}
        message = event.get("message") or {}
        sender = event.get("sender") or {}
        sender_id = sender.get("sender_id") or {}
        identity = OperatorIdentity.from_dict(sender_id)
        event_id = str(header.get("event_id") or "")
        message_id = str(message.get("message_id") or "")
        if not event_id or not message_id or not identity.ids():
            raise FeishuError("invalid_event", "event_id, message_id and sender identity are required")
        try:
            content = json.loads(str(message.get("content") or "{}"))
        except json.JSONDecodeError as exc:
            raise FeishuError("invalid_event", "message content is not JSON") from exc
        text = str(content.get("text") or "").strip()
        for mention in message.get("mentions") or []:
            key = str((mention or {}).get("key") or "")
            if key:
                text = text.replace(key, "").strip()
        if message.get("message_type") not in (None, "", "text"):
            return {"ok": True, "ignored": True}
        if not text.startswith("/dt"):
            return {"ok": True, "ignored": True}
        client = self.store.client_for(identity)
        self.store.enqueue(
            client,
            "commands",
            event_id,
            {
                "event_id": event_id,
                "message_id": message_id,
                "identity": identity.public_dict(),
                "text": text,
            },
        )
        log.emit("feishu.bridge.event", client=client, event_id=_digest(event_id)[:12])
        return {"ok": True}

    def flush_responses(self) -> int:
        count = 0
        root = self.store.root / "responses"
        paths = sorted(root.glob("*/*.json")) if root.is_dir() else []
        if not paths:
            return 0
        config = self.app_config()
        secret = load_app_secret(config)
        for path in paths:
            item = _read_envelope(path)
            message_id = str(item.get("message_id") or "")
            if message_id:
                self.reply_transport.reply(config, secret, message_id, str(item.get("text") or ""))
            path.unlink(missing_ok=True)
            count += 1
        return count


class BridgeHTTPServer(ThreadingHTTPServer):
    application: BridgeApplication


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    @property
    def app(self) -> BridgeApplication:
        return self.server.application  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            self._json(
                200,
                {
                    "ok": True,
                    "service": "dual-tmux-feishu-bridge",
                    "configured": bool(self.app.config or (home_dir() / "feishu" / "config.json").is_file()),
                },
            )
            return
        if parsed.path != "/feishu/callback":
            self._json(404, {"ok": False, "error": "not found"})
            return
        query = urllib.parse.parse_qs(parsed.query)
        try:
            identity = self.app.callback((query.get("state") or [""])[0], (query.get("code") or [""])[0])
            self._json(200, {"ok": True, "bound": bool(identity.ids())})
        except FeishuError as exc:
            self._json(400, exc.as_dict())

    def do_POST(self) -> None:
        if self.path != "/feishu/events":
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_ENVELOPE:
            self._json(413, {"ok": False, "error": "invalid body size"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            result = self.app.event(payload)
            self._json(200, result)
        except (json.JSONDecodeError, FeishuError) as exc:
            body = exc.as_dict() if isinstance(exc, FeishuError) else {"ok": False, "error": "invalid JSON"}
            self._json(400, body)


def serve_bridge(host: str, port: int, application: BridgeApplication | None = None) -> None:
    server = BridgeHTTPServer((host, port), BridgeHandler)
    server.application = application or BridgeApplication()
    server.timeout = 2
    print(f"dt feishu bridge  http://{host}:{port}  (Ctrl-C stop)")
    try:
        while True:
            server.handle_request()
            try:
                server.application.flush_responses()
            except FeishuError as exc:
                log.emit("feishu.bridge.reply.reject", reason=exc.code)
    finally:
        server.server_close()
