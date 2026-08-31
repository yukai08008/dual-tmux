"""Feishu pairing, authorization and command-dispatch security boundary.

This module deliberately stores no OAuth access token.  Tokens live only for the
duration of a callback exchange; only stable Feishu identity IDs are persisted.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import stat
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from . import log
from .control import ControlError, ControlService, get_control_service
from .paths import home_dir

PAIR_TTL_SECONDS = 10 * 60
CONFIRM_TTL_SECONDS = 5 * 60
REPLAY_TTL_SECONDS = 24 * 60 * 60
_IDENTITY_KEYS = ("open_id", "union_id", "user_id")
_FORBIDDEN = {"upgrade", "hotfix", "cron", "shell", "ssh", "config", "push", "pull"}


class FeishuError(RuntimeError):
    def __init__(self, code: str, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail or {}

    def as_dict(self) -> dict:
        return {"ok": False, "error": {"code": self.code, "message": str(self), "detail": self.detail}}


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    redirect_uri: str
    secret_file: str = ""
    allowlist: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> FeishuConfig:
        return cls(
            app_id=str(data.get("app_id") or "").strip(),
            redirect_uri=str(data.get("redirect_uri") or "").strip(),
            secret_file=str(data.get("secret_file") or "").strip(),
            allowlist=tuple(str(item).strip() for item in data.get("allowlist") or [] if str(item).strip()),
        )


@dataclass(frozen=True)
class OperatorIdentity:
    open_id: str = ""
    union_id: str = ""
    user_id: str = ""
    name: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> OperatorIdentity:
        return cls(**{key: str(data.get(key) or "") for key in (*_IDENTITY_KEYS, "name")})

    def ids(self) -> set[str]:
        return {getattr(self, key) for key in _IDENTITY_KEYS if getattr(self, key)}

    def public_dict(self) -> dict:
        return asdict(self)


def feishu_dir() -> Path:
    return home_dir() / "feishu"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        path.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise FeishuError("invalid_state", f"invalid Feishu state file: {path}")


def save_config(config: FeishuConfig) -> Path:
    if not config.app_id or not config.redirect_uri:
        raise FeishuError("invalid_config", "app_id and redirect_uri are required")
    path = feishu_dir() / "config.json"
    _atomic_json(path, {**asdict(config), "allowlist": list(config.allowlist)})
    return path


def load_feishu_config() -> FeishuConfig:
    path = feishu_dir() / "config.json"
    if not path.is_file():
        raise FeishuError("not_configured", "Feishu is not configured")
    config = FeishuConfig.from_dict(_read_json(path, {}))
    if not config.app_id or not config.redirect_uri:
        raise FeishuError("invalid_config", "app_id and redirect_uri are required")
    return config


def load_app_secret(config: FeishuConfig) -> str:
    env_secret = os.environ.get("DT_FEISHU_APP_SECRET", "").strip()
    if env_secret:
        return env_secret
    if not config.secret_file:
        raise FeishuError(
            "secret_missing",
            "set DT_FEISHU_APP_SECRET or configure a mode-0600 secret file",
        )
    path = Path(config.secret_file).expanduser()
    try:
        link_info = path.lstat()
        info = path.stat()
    except OSError as exc:
        raise FeishuError("secret_unreadable", f"cannot read secret file: {path}") from exc
    if (
        stat.S_ISLNK(link_info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.getuid()
    ):
        raise FeishuError(
            "secret_permissions",
            "Feishu secret file must be owned by the current user, mode 0600, and not a symlink",
        )
    secret = path.read_text(encoding="utf-8").strip()
    if not secret:
        raise FeishuError("secret_missing", "Feishu secret file is empty")
    return secret


class OAuthTransport(Protocol):
    def exchange(self, config: FeishuConfig, app_secret: str, code: str) -> OperatorIdentity: ...


class FeishuOAuthTransport:
    """Minimal Feishu OAuth exchange used by the CLI callback and future Web API."""

    token_url = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    user_url = "https://open.feishu.cn/open-apis/authen/v1/user_info"

    @staticmethod
    def _json_request(url: str, *, payload: dict | None = None, token: str = "") -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise FeishuError("oauth_transport", "Feishu OAuth request failed") from exc

    def exchange(self, config: FeishuConfig, app_secret: str, code: str) -> OperatorIdentity:
        token_data = self._json_request(
            self.token_url,
            payload={
                "grant_type": "authorization_code",
                "client_id": config.app_id,
                "client_secret": app_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
            },
        )
        if token_data.get("code") not in (None, 0):
            raise FeishuError("oauth_rejected", str(token_data.get("msg") or "OAuth code rejected"))
        token = str(token_data.get("access_token") or (token_data.get("data") or {}).get("access_token") or "")
        if not token:
            raise FeishuError("oauth_rejected", "Feishu returned no access token")
        user_data = self._json_request(self.user_url, token=token)
        if user_data.get("code") not in (None, 0):
            raise FeishuError("identity_rejected", str(user_data.get("msg") or "identity lookup failed"))
        return OperatorIdentity.from_dict(user_data.get("data") or user_data)


class _StateStore:
    """Small locked local state store; token-like values are persisted only as hashes."""

    def __init__(self, path: Path | None = None, clock=time.time):
        self.path = path or feishu_dir() / "state.json"
        self.lock_path = self.path.with_suffix(".lock")
        self.clock = clock

    def mutate(self, callback):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            data = _read_json(self.path, {"pairing": {}, "events": {}, "confirmations": {}})
            now = self.clock()
            for bucket in ("pairing", "events", "confirmations"):
                values = data.setdefault(bucket, {})
                data[bucket] = {key: item for key, item in values.items() if float(item.get("expires_at", 0)) > now}
            result = callback(data, now)
            _atomic_json(self.path, data)
            return result


class PairingService:
    def __init__(self, *, store: _StateStore | None = None, transport: OAuthTransport | None = None):
        self.store = store or _StateStore()
        self.transport = transport or FeishuOAuthTransport()

    def begin(self, config: FeishuConfig | None = None, ttl: int = PAIR_TTL_SECONDS) -> dict:
        cfg = config or load_feishu_config()
        state = secrets.token_urlsafe(32)
        digest = _digest(state)

        def add(data, now):
            data["pairing"][digest] = {"expires_at": now + max(30, ttl)}

        self.store.mutate(add)
        query = urllib.parse.urlencode({"app_id": cfg.app_id, "redirect_uri": cfg.redirect_uri, "state": state})
        log.emit("feishu.pair.begin", state=digest[:12])
        return {
            "state": state,
            "expires_in": max(30, ttl),
            "authorization_url": f"https://accounts.feishu.cn/open-apis/authen/v1/authorize?{query}",
        }

    def _consume_state(self, state: str) -> None:
        self._consume_state_digest(_digest(state))

    def _consume_state_digest(self, digest: str) -> None:

        def consume(data, _now):
            if not digest or digest not in data["pairing"]:
                raise FeishuError("invalid_state", "pairing state is unknown, expired, or already used")
            del data["pairing"][digest]

        self.store.mutate(consume)

    def complete_identity_digest(
        self, state_digest: str, identity: OperatorIdentity, config: FeishuConfig | None = None
    ) -> OperatorIdentity:
        """Complete a Hub-routed pairing without exposing the raw state to the Hub."""
        cfg = config or load_feishu_config()
        self._consume_state_digest(state_digest)
        if not identity.ids():
            raise FeishuError("identity_missing", "Feishu returned no stable operator ID")
        if cfg.allowlist and not identity.ids().intersection(cfg.allowlist):
            raise FeishuError("operator_not_allowed", "operator is not in the configured allowlist")
        bind_operator(identity)
        log.emit("feishu.pair.ok", operator=_operator_hash(identity))
        return identity

    def callback(self, state: str, code: str, config: FeishuConfig | None = None) -> OperatorIdentity:
        cfg = config or load_feishu_config()
        self._consume_state(state)
        if not code:
            raise FeishuError("missing_code", "OAuth callback code is required")
        try:
            identity = self.transport.exchange(cfg, load_app_secret(cfg), code)
            if not identity.ids():
                raise FeishuError("identity_missing", "Feishu returned no stable operator ID")
            if cfg.allowlist and not identity.ids().intersection(cfg.allowlist):
                raise FeishuError("operator_not_allowed", "operator is not in the configured allowlist")
            bind_operator(identity)
            log.emit("feishu.pair.ok", operator=_operator_hash(identity))
            return identity
        except FeishuError as exc:
            log.emit("feishu.pair.reject", reason=exc.code)
            raise


def _bindings_path() -> Path:
    return feishu_dir() / "bindings.json"


def list_bindings() -> list[OperatorIdentity]:
    return [OperatorIdentity.from_dict(item) for item in _read_json(_bindings_path(), [])]


def bind_operator(identity: OperatorIdentity) -> None:
    current = list_bindings()
    ids = identity.ids()
    merged = [item for item in current if not item.ids().intersection(ids)]
    merged.append(identity)
    _atomic_json(_bindings_path(), [item.public_dict() for item in merged])


def unbind_operator(identity_id: str = "") -> int:
    current = list_bindings()
    kept = [] if not identity_id else [item for item in current if identity_id not in item.ids()]
    _atomic_json(_bindings_path(), [item.public_dict() for item in kept])
    removed = len(current) - len(kept)
    log.emit("feishu.unbind", removed=removed)
    return removed


def _operator_hash(identity: OperatorIdentity) -> str:
    return _digest("\0".join(sorted(identity.ids())))[:16]


def is_bound(identity: OperatorIdentity) -> bool:
    ids = identity.ids()
    if not ids or not any(ids.intersection(item.ids()) for item in list_bindings()):
        return False
    config_path = feishu_dir() / "config.json"
    if not config_path.is_file():
        return True
    allowlist = FeishuConfig.from_dict(_read_json(config_path, {})).allowlist
    return not allowlist or bool(ids.intersection(allowlist))


@dataclass(frozen=True)
class FeishuCommand:
    action: str
    name: str = ""
    text: str = ""
    token: str = ""


def parse_command(message: str) -> FeishuCommand:
    raw = (message or "").strip()
    if not raw.startswith("/dt") or (len(raw) > 3 and not raw[3].isspace()):
        raise FeishuError("invalid_command", "command must start with /dt")
    body = raw[3:].strip()
    if not body:
        raise FeishuError("invalid_command", "missing /dt action")
    action, _, rest = body.partition(" ")
    action = action.lower()
    rest = rest.strip()
    if action in _FORBIDDEN:
        raise FeishuError("command_forbidden", f"/dt {action} is not available through Feishu")
    if action == "ls":
        if rest:
            raise FeishuError("invalid_command", "/dt ls takes no arguments")
        return FeishuCommand(action)
    if action == "send":
        name, separator, text = rest.partition(" ")
        if not separator or not name or not text.strip():
            raise FeishuError("invalid_command", "usage: /dt send <name> <text>")
        return FeishuCommand(action, name=name, text=text)
    if action in {"show", "health", "freeze", "resume", "recover"}:
        parts = rest.split()
        if len(parts) != 1:
            raise FeishuError("invalid_command", f"usage: /dt {action} <name>")
        return FeishuCommand(action, name=parts[0])
    if action in {"drop", "rm"}:
        parts = rest.split()
        if len(parts) not in {1, 2}:
            raise FeishuError("invalid_command", f"usage: /dt {action} <name> [confirm-token]")
        return FeishuCommand(action, name=parts[0], token=parts[1] if len(parts) == 2 else "")
    raise FeishuError("command_forbidden", f"unsupported Feishu command: {action}")


class FeishuDispatcher:
    def __init__(self, service: ControlService | None = None, *, store: _StateStore | None = None):
        self.service = service or get_control_service()
        self.store = store or _StateStore()

    def _accept_event(self, event_id: str) -> None:
        digest = _digest(event_id)

        def add(data, now):
            if not event_id:
                raise FeishuError("event_id_required", "event_id is required")
            if digest in data["events"]:
                raise FeishuError("event_replayed", "event_id was already processed")
            data["events"][digest] = {"expires_at": now + REPLAY_TTL_SECONDS}

        self.store.mutate(add)

    def _issue_confirmation(self, identity: OperatorIdentity, command: FeishuCommand) -> str:
        token = secrets.token_urlsafe(24)
        digest = _digest(token)

        def add(data, now):
            data["confirmations"][digest] = {
                "expires_at": now + CONFIRM_TTL_SECONDS,
                "operator": _operator_hash(identity),
                "action": command.action,
                "name": command.name,
            }

        self.store.mutate(add)
        return token

    def _consume_confirmation(self, identity: OperatorIdentity, command: FeishuCommand) -> None:
        digest = _digest(command.token)

        def consume(data, _now):
            item = data["confirmations"].get(digest)
            expected = (_operator_hash(identity), command.action, command.name)
            actual = (item or {}).get("operator"), (item or {}).get("action"), (item or {}).get("name")
            if not command.token or actual != expected:
                raise FeishuError("confirmation_invalid", "confirmation token is invalid, expired, or mismatched")
            del data["confirmations"][digest]

        self.store.mutate(consume)

    def dispatch(self, event_id: str, identity: OperatorIdentity, message: str) -> dict:
        operator = _operator_hash(identity)
        try:
            self._accept_event(event_id)
            if not is_bound(identity):
                raise FeishuError("operator_unbound", "operator has not been paired")
            command = parse_command(message)
            if command.action in {"drop", "rm"} and not command.token:
                token = self._issue_confirmation(identity, command)
                result = {
                    "ok": False,
                    "confirmation_required": True,
                    "action": command.action,
                    "name": command.name,
                    "token": token,
                    "expires_in": CONFIRM_TTL_SECONDS,
                }
                log.emit("feishu.command.confirm", operator=operator, action=command.action, name=command.name)
                return result
            if command.action in {"drop", "rm"}:
                self._consume_confirmation(identity, command)
            result = self._execute(command)
            log.emit("feishu.command.ok", operator=operator, action=command.action, name=command.name)
            return {"ok": True, "result": result.as_dict()}
        except (FeishuError, ControlError) as exc:
            code = getattr(exc, "code", "operation_failed")
            log.emit("feishu.command.reject", operator=operator, reason=code)
            if isinstance(exc, ControlError):
                raise FeishuError(code, str(exc), detail=exc.detail) from exc
            raise

    def _execute(self, command: FeishuCommand):
        if command.action == "ls":
            return self.service.list_tunnels()
        if command.action == "show":
            return self.service.get_tunnel(command.name)
        if command.action == "send":
            return self.service.send(command.name, command.text, "bullet")
        if command.action == "health":
            return self.service.probe_health(command.name)
        if command.action == "freeze":
            return self.service.freeze(command.name, None, "auto")
        if command.action == "resume":
            return self.service.resume(command.name, False)
        if command.action == "recover":
            return self.service.recover(command.name, force=False)
        if command.action == "drop":
            return self.service.drop(command.name, confirm=command.name)
        if command.action == "rm":
            return self.service.remove_tunnel(command.name, confirm=command.name, kill=False)
        raise FeishuError("command_forbidden", f"unsupported Feishu command: {command.action}")


def status() -> dict:
    path = feishu_dir() / "config.json"
    config = FeishuConfig.from_dict(_read_json(path, {})) if path.is_file() else None
    bindings = list_bindings()
    return {
        "configured": bool(config and config.app_id and config.redirect_uri),
        "app_id": config.app_id if config else "",
        "redirect_uri": config.redirect_uri if config else "",
        "secret_file": config.secret_file if config else "",
        "allowlist": list(config.allowlist) if config else [],
        "secret_source": "env" if os.environ.get("DT_FEISHU_APP_SECRET") else ("file" if config and config.secret_file else "missing"),
        "allowlist_count": len(config.allowlist) if config else 0,
        "bindings": [item.public_dict() for item in bindings],
    }
