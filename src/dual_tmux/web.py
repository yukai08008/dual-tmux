from __future__ import annotations

import errno
import json
import os
import re
import threading
import time
import webbrowser
import zipfile
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import oc as oc_ops
from . import skillmgr
from . import tmux as tmux_ops
from .config import load_config
from .control import ControlError, get_control_service
from .paneparse import parse_pane, parser_id_for_side
from .paths import home_dir
from .recovery import read_state as read_health_state
from .store import normalize_dt

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
_LIFECYCLE_LOCK = threading.Lock()
_WEB_STATE_LOCK = threading.Lock()


_CLIENT_DISCONNECT_ERRNOS = {
    errno.EBADF,
    errno.EPIPE,
    errno.ECONNABORTED,
    errno.ECONNRESET,
    errno.ENOTCONN,
}


def _is_client_disconnect(exc: BaseException | None) -> bool:
    """Recognize socket failures caused by a browser closing its request."""
    return isinstance(
        exc, (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)
    ) or (isinstance(exc, OSError) and exc.errno in _CLIENT_DISCONNECT_ERRNOS)


def _opencode_auto(text: str) -> bool | None:
    """Return the input mode without mistaking a running status for manual mode."""
    matches = list(
        re.finditer(
            r"\bBuild(?P<auto>\s+auto)?\s*[·•][^\n]*", text or "", re.IGNORECASE
        )
    )
    running_at = (text or "").lower().rfind("esc interrupt")
    if running_at >= 0:
        before = [match for match in matches if match.start() < running_at]
        # The status immediately before `esc interrupt` describes the running
        # request and omits `auto`; the preceding prompt describes input mode.
        matches = before[:-1] if before else []
    return bool(matches[-1].group("auto")) if matches else None


def _web_state_path() -> Path:
    return home_dir() / "web-state.json"


def _clean_web_state(data: object) -> dict:
    src = data if isinstance(data, dict) else {}
    history_src = src.get("history") if isinstance(src.get("history"), dict) else {}
    history: dict[str, dict] = {}
    for name, raw in list(history_src.items())[:50]:
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 160
            or not isinstance(raw, dict)
        ):
            continue
        thread = []
        for item in (raw.get("thread") if isinstance(raw.get("thread"), list) else [])[
            -60:
        ]:
            if not isinstance(item, dict):
                continue
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            thread.append(
                {
                    "kind": str(item.get("kind") or "ans")[:16],
                    "text": str(item.get("text") or "")[:8000],
                    "extra": {
                        str(k)[:32]: str(v)[:300] for k, v in list(extra.items())[:8]
                    },
                }
            )
        log = []
        for item in (raw.get("log") if isinstance(raw.get("log"), list) else [])[-100:]:
            if isinstance(item, dict):
                log.append(
                    {
                        "kind": str(item.get("kind") or "idle")[:16],
                        "text": str(item.get("text") or "")[:1000],
                    }
                )
        try:
            visits = int(raw.get("visits") or 0)
        except (TypeError, ValueError):
            visits = 0
        pending_raw = raw.get("pending") if isinstance(raw.get("pending"), dict) else {}
        pending = None
        pending_id = str(pending_raw.get("id") or "")[:80]
        if pending_id:
            status = str(pending_raw.get("status") or "pending")[:16]
            if status not in {"pending", "running", "attention"}:
                status = "pending"
            pending = {
                "id": pending_id,
                "status": status,
                "startedAt": str(pending_raw.get("startedAt") or "")[:40],
                "baselineCompletion": str(pending_raw.get("baselineCompletion") or "")[
                    :80
                ],
            }
        history[name] = {
            "name": name,
            "firstVisitedAt": str(raw.get("firstVisitedAt") or "")[:40],
            "lastVisitedAt": str(raw.get("lastVisitedAt") or "")[:40],
            "visits": max(0, min(visits, 1_000_000)),
            "finalOp": str(raw.get("finalOp") or "gray")[:12],
            "finalRun": str(raw.get("finalRun") or "gray")[:12],
            "lastCompletion": str(raw.get("lastCompletion") or "")[:80],
            "pending": pending,
            "thread": thread,
            "log": log,
        }
    open_tabs = []
    for name in src.get("open_tabs") if isinstance(src.get("open_tabs"), list) else []:
        if isinstance(name, str) and name in history and name not in open_tabs:
            open_tabs.append(name)
        if len(open_tabs) >= 20:
            break
    active = str(src.get("active") or "")
    return {
        "version": 1,
        "open_tabs": open_tabs,
        "active": active if active in open_tabs else "",
        "history": history,
    }


def _load_web_state() -> dict:
    path = _web_state_path()
    if not path.is_file():
        return _clean_web_state({})
    try:
        return _clean_web_state(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return _clean_web_state({})


def _save_web_state(data: object) -> dict:
    cleaned = _clean_web_state(data)
    path = _web_state_path()
    with _WEB_STATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    return cleaned


def _multipart(raw: bytes, content_type: str) -> tuple[dict[str, str], list[bytes]]:
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + content_type.encode("ascii", "replace")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + raw
    )
    fields: dict[str, str] = {}
    files: list[bytes] = []
    if not message.is_multipart():
        raise SystemExit("[err] invalid upload")
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition") or ""
        payload = part.get_payload(decode=True) or b""
        if name == "files":
            files.append(payload)
        else:
            fields[name] = payload.decode("utf-8", "replace")
    return fields, files


def _tunnels() -> list[dict]:
    service = get_control_service()
    nodes = service.list_tunnel_nodes()
    rows = []
    for node in nodes:
        raw = service.repository.get_raw(node.name)
        op = node.op
        run = node.run
        op_info = tmux_ops.pane_info(op) if op else {}
        run_info = tmux_ops.pane_info(run) if run else {}
        trig = node.trigger
        bull = node.bullet
        trig_ses = trig.session if trig else None
        bull_ses = bull.session if bull else None
        raw_trig = raw.get("trigger") or {}
        raw_bull = raw.get("bullet") or {}
        rows.append(
            {
                "name": node.name,
                "dst": node.is_dst,
                "op": op,
                "run": run,
                "op_live": bool(op) and tmux_ops.has_session(op),
                "run_live": bool(run) and tmux_ops.has_session(run),
                "op_cmd": op_info.get("cmd") or "",
                "run_cmd": run_info.get("cmd") or "",
                "trigger": trig_ses.slug if trig_ses else (raw_trig.get("slug") or ""),
                "bullet": bull_ses.slug if bull_ses else (raw_bull.get("slug") or ""),
                "trigger_model": trig_ses.model
                if trig_ses
                else (raw_trig.get("model") or ""),
                "bullet_model": bull_ses.model
                if bull_ses
                else (raw_bull.get("model") or ""),
                "trigger_tool": trig_ses.tool
                if trig_ses
                else (raw_trig.get("tool") or "opencode"),
                "bullet_tool": bull_ses.tool
                if bull_ses
                else (raw_bull.get("tool") or "opencode"),
                "trigger_client": (
                    trig_ses.client.model_dump(mode="json", exclude_none=True)
                    if trig_ses and trig_ses.client
                    else (raw_trig.get("agent_client") or {})
                ),
                "bullet_client": (
                    bull_ses.client.model_dump(mode="json", exclude_none=True)
                    if bull_ses and bull_ses.client
                    else (raw_bull.get("agent_client") or {})
                ),
                "auto_recover": node.auto_recover,
                "health": read_health_state(node.name),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def _pane_name(data: dict, side: str) -> str:
    if side == "op":
        return data.get("op") or ""
    return data.get("run") or ""


def _switch_trigger_auto(name: str) -> dict:
    """Restart a tunnel's bound trigger session in OpenCode auto mode."""
    with _LIFECYCLE_LOCK:
        service = get_control_service()
        raw = service.repository.get_raw(name)
        node = service.get_tunnel_node(name)
        op = node.op
        trigger = raw.get("trigger") or {}
        if not op or not tmux_ops.has_session(op):
            raise SystemExit("[err] trigger pane is offline")
        if (trigger.get("tool") or "opencode") != "opencode":
            raise SystemExit("[err] trigger is not OpenCode")
        if not trigger.get("session_id"):
            raise SystemExit(
                "[err] trigger has no frozen session id; run dt freeze first"
            )
        if _opencode_auto(_capture(op)):
            return {"ok": True, "changed": False, "auto": True, "pane": op}
        if tmux_ops.pane_command(op) == "opencode" and not tmux_ops.quit_opencode(op):
            raise SystemExit("[err] failed to stop current trigger OpenCode")
        tmux_ops.start_opencode(op, oc_ops.resume_cmd(trigger))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if _opencode_auto(_capture(op)):
                return {"ok": True, "changed": True, "auto": True, "pane": op}
            if not tmux_ops.has_session(op):
                break
            time.sleep(0.4)
        raise SystemExit(
            "[err] trigger auto mode did not become ready within 20 seconds"
        )


def _mtime_iso(path: Path) -> str:
    if not path.is_file() and not path.is_dir():
        return ""
    try:
        ts = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _sync_info(data: dict) -> dict:
    cfg = load_config()
    source = cfg.client
    trigger = data.get("trigger") or {}
    slug = trigger.get("slug") or ""
    op = data.get("op") or ""
    run = data.get("run") or ""
    sessions = Path(
        os.environ.get("DT_SESSIONS_HOME", Path.home() / "sessions")
    ).expanduser()
    oc_json = sessions / "opencode" / source / f"{slug}.json" if slug else Path()
    tmux_dir = sessions / "tmux" / source
    last_link = tmux_dir / "last"
    oc_lock = home_dir() / "locks" / "persist-opencode"
    tmux_lock = home_dir() / "locks" / "persist-tmux"
    oc_busy = oc_lock.is_dir()
    tmux_busy = tmux_lock.is_dir()
    return {
        "source": source,
        "op": op,
        "run": run,
        "op_live": bool(op) and tmux_ops.has_session(op),
        "run_live": bool(run) and tmux_ops.has_session(run),
        "oc_slug": slug,
        "oc_file": str(oc_json) if slug else "",
        "oc_mtime": _mtime_iso(oc_json) if slug else "",
        "tmux_last": _mtime_iso(last_link),
        "tmux_dir": str(tmux_dir),
        "oc_busy": oc_busy,
        "tmux_busy": tmux_busy,
        "busy": oc_busy or tmux_busy,
    }


def _capture(name: str) -> str:
    if not name:
        return "(no pane)"
    if not tmux_ops.has_session(name):
        return f"(tmux {name} not running)"
    return tmux_ops.capture_pane(name, -500) or "(empty pane)"


from .web_pages import (
    dashboard_page,
    doctor_page,
    events_page,
    feishu_page,
    guide_page,
    memory_page,
    skills_page,
    tunnels_page,
)


class WebHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        import sys

        if _is_client_disconnect(sys.exc_info()[1]):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(
        self,
        code: int,
        body: str | bytes,
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _same_origin(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        request_netloc = (self.headers.get("Host") or "").lower()
        return (
            parsed.scheme == "http"
            and host in {"127.0.0.1", "localhost"}
            and parsed.netloc.lower() == request_netloc
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/tunnels":
            self._send(200, json.dumps(_tunnels()), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/health":
            name = (qs.get("t") or [""])[0]
            if name:
                try:
                    from datanode.adapters import to_legacy_tunnel

                    node = get_control_service().get_tunnel_node(name)
                    data = to_legacy_tunnel(node)
                except (ControlError, KeyError, SystemExit) as exc:
                    self._send(
                        404,
                        json.dumps({"error": str(exc)}),
                        "application/json; charset=utf-8",
                    )
                    return
                payload = read_health_state(data.get("name") or name)
            else:
                payload = {row["name"]: row["health"] for row in _tunnels()}
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/capabilities":
            result = get_control_service().capabilities()
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/operations":
            result = get_control_service().operations()
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/config":
            cfg = load_config()
            self._send(
                200,
                json.dumps(
                    {
                        "mode": cfg.mode,
                        "client": cfg.client,
                        "server": cfg.server,
                        "ssh_port": cfg.ssh_port,
                        "user": cfg.user,
                        "workspace": cfg.workspace,
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/feishu/status":
            from .feishu import status

            payload = status()
            cfg = load_config()
            payload["bridge"] = cfg.server if cfg.hub_enabled else "local-only"
            if cfg.hub_enabled:
                from .feishu_bridge import hub_feishu_status

                remote = hub_feishu_status(cfg)
                if remote:
                    payload["installed"] = bool(remote.get("installed"))
                    payload["configured"] = payload["installed"]
                    payload["daemon"] = remote.get("daemon") or payload["daemon"]
                    payload["ws_topology"] = "hub-persistent"
            else:
                payload["ws_topology"] = "local-standalone"
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/events":
            result = get_control_service().events(
                limit=min(500, int((qs.get("limit") or ["100"])[0] or 100)),
                kind=(qs.get("kind") or [""])[0],
                name=(qs.get("t") or [""])[0],
            )
            self._send(200, json.dumps(result.data), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/memory":
            name = (qs.get("t") or [""])[0]
            result = get_control_service().memory(name)
            self._send(200, json.dumps(result.data), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/web-state":
            self._send(
                200, json.dumps(_load_web_state()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/tunnel":
            name = (qs.get("t") or [""])[0]
            try:
                data = get_control_service().get_tunnel_readonly(name).data
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            op = data.get("op") or ""
            run = data.get("run") or ""
            op_text = _capture(op)
            run_text = _capture(run)
            payload = {
                "name": data.get("name"),
                "op": op,
                "run": run,
                "dst": oc_ops.is_dst(data),
                "op_live": bool(op) and tmux_ops.has_session(op),
                "run_live": bool(run) and tmux_ops.has_session(run),
                "op_cmd": tmux_ops.pane_info(op).get("cmd") if op else "",
                "run_cmd": tmux_ops.pane_info(run).get("cmd") if run else "",
                "op_text": op_text,
                "run_text": run_text,
                "op_auto": _opencode_auto(op_text),
                "op_parsed": parse_pane(
                    op_text, parser_id_for_side(data.get("trigger"))
                ).as_dict(),
                "run_parsed": parse_pane(
                    run_text, parser_id_for_side(data.get("bullet"))
                ).as_dict(),
                "trigger_model": (data.get("trigger") or {}).get("model") or "",
                "bullet_model": (data.get("bullet") or {}).get("model") or "",
                "trigger_tool": (data.get("trigger") or {}).get("tool") or "opencode",
                "bullet_tool": (data.get("bullet") or {}).get("tool") or "opencode",
                "trigger_client": (data.get("trigger") or {}).get("agent_client") or {},
                "bullet_client": (data.get("bullet") or {}).get("agent_client") or {},
                "auto_recover": bool(data.get("auto_recover")),
                "health": read_health_state(data.get("name") or name),
                "sync": _sync_info(data),
            }
            self._send(200, json.dumps(payload), "application/json; charset=utf-8")
            return
        if parsed.path in {"/api/ownership", "/api/resume/plan"}:
            name = (qs.get("t") or [""])[0]
            try:
                service = get_control_service()
                result = (
                    service.cached_ownership(name)
                    if parsed.path == "/api/ownership"
                    else service.cached_resume_plan(name)
                )
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/models":
            q = ((qs.get("q") or [""])[0] or "").lower()
            models = oc_ops.list_models()
            if q:
                parts = [p for p in q.split() if p]
                models = [m for m in models if all(p in m.lower() for p in parts)]
            self._send(200, json.dumps(models[:80]), "application/json; charset=utf-8")
            return
        if parsed.path in {"/", "/dashboard"}:
            self._send(200, dashboard_page())
            return
        if parsed.path in {"/tunnels", "/t"}:
            self._send(200, tunnels_page((qs.get("t") or [""])[0]))
            return
        if parsed.path == "/feishu":
            self._send(200, feishu_page())
            return
        if parsed.path in {"/guide", "/help"}:
            self._send(200, guide_page())
            return
        if parsed.path in {"/skills"}:
            self._send(200, skills_page())
            return
        if parsed.path == "/memory":
            self._send(200, memory_page())
            return
        if parsed.path == "/events":
            self._send(200, events_page())
            return
        if parsed.path == "/doctor":
            self._send(200, doctor_page())
            return
        if parsed.path == "/api/skills":
            self._send(
                200,
                json.dumps(skillmgr.list_catalog()),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/skill-tree":
            name = (qs.get("name") or [""])[0]
            try:
                self._send(
                    200,
                    json.dumps(skillmgr.skill_tree(name)),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    404,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-installed-file":
            name = (qs.get("name") or [""])[0]
            rel = (qs.get("rel") or [""])[0]
            try:
                body = skillmgr.read_skill_file(name, rel)
                self._send(
                    200,
                    json.dumps({"body": body, "rel": rel}),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    404,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-preview":
            src = (qs.get("src") or [""])[0]
            try:
                self._send(
                    200,
                    json.dumps(skillmgr.preview_source(src)),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    400,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-file":
            src = (qs.get("src") or [""])[0]
            rel = (qs.get("rel") or [""])[0]
            try:
                body = skillmgr.read_source_file(src, rel)
                self._send(
                    200,
                    json.dumps({"body": body, "rel": rel}),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    400,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-body":
            name = (qs.get("name") or [""])[0]
            try:
                self._send(
                    200,
                    json.dumps({"body": skillmgr.skill_body(name)}),
                    "application/json; charset=utf-8",
                )
            except SystemExit as exc:
                self._send(
                    404,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        if parsed.path == "/api/skill-log":
            n = int((qs.get("n") or ["40"])[0] or 40)
            self._send(
                200,
                json.dumps(skillmgr.read_log(limit=n)),
                "application/json; charset=utf-8",
            )
            return
        self._send(404, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self._same_origin():
            self._send(
                403,
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "origin_rejected",
                            "message": "Web control writes require a local same-origin request",
                            "detail": {},
                        },
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 30 * 1024 * 1024:
            self._send(413, "[err] upload is too large", "text/plain; charset=utf-8")
            return
        raw_bytes = self.rfile.read(length)
        if parsed.path.startswith("/api/feishu/"):
            from .feishu import AppRegistrationService, FeishuError, uninstall

            try:
                payload = json.loads(raw_bytes.decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise FeishuError("invalid_request", "JSON object required")
                if parsed.path == "/api/feishu/pair":
                    if payload:
                        raise FeishuError(
                            "invalid_request", "scan-to-create takes no App credentials"
                        )
                    result = AppRegistrationService().begin()
                    import segno

                    result["qr"] = segno.make(result["authorization_url"]).svg_data_uri(
                        scale=5
                    )
                    result["ok"] = True
                elif parsed.path == "/api/feishu/poll":
                    result = {"ok": True, **AppRegistrationService().poll()}
                elif parsed.path == "/api/feishu/unbind":
                    result = {"ok": True, **uninstall()}
                else:
                    self._send(404, "not found")
                    return
            except (json.JSONDecodeError, FeishuError) as exc:
                body = (
                    exc.as_dict()
                    if isinstance(exc, FeishuError)
                    else {
                        "ok": False,
                        "error": {
                            "code": "invalid_json",
                            "message": "invalid JSON",
                            "detail": {},
                        },
                    }
                )
                self._send(400, json.dumps(body), "application/json; charset=utf-8")
                return
            self._send(200, json.dumps(result), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/web-state":
            try:
                payload = json.loads(raw_bytes.decode("utf-8"))
                saved = _save_web_state(payload)
            except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps(saved), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/skill-upload":
            try:
                fields, files = _multipart(
                    raw_bytes, self.headers.get("Content-Type") or ""
                )
                paths = json.loads(fields.get("paths") or "[]")
                if not isinstance(paths, list) or not all(
                    isinstance(p, str) for p in paths
                ):
                    raise SystemExit("[err] invalid upload paths")
                imported = skillmgr.import_upload(
                    fields.get("kind") or "", paths, files
                )
            except (SystemExit, ValueError, zipfile.BadZipFile) as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(
                200,
                json.dumps({"ok": True, "name": imported}),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/memory/fact":
            raw = raw_bytes.decode("utf-8")
            form = parse_qs(raw)
            value_raw = (form.get("value") or [""])[0]
            try:
                value = json.loads(value_raw)
            except json.JSONDecodeError:
                value = value_raw
            try:
                result = get_control_service().put_memory_fact(
                    (form.get("key") or [""])[0],
                    value,
                    (form.get("t") or [""])[0],
                )
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/memory/note":
            raw = raw_bytes.decode("utf-8")
            form = parse_qs(raw)
            try:
                result = get_control_service().add_memory_note(
                    (form.get("t") or [""])[0],
                    (form.get("body") or [""])[0],
                    (form.get("title") or [""])[0],
                )
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/doctor/run":
            result = get_control_service().doctor()
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        raw = raw_bytes.decode("utf-8")
        form = parse_qs(raw)
        name = (form.get("t") or [""])[0]
        if parsed.path == "/api/resume":
            try:
                force = (form.get("force") or ["0"])[0] == "1"
                if force and (form.get("confirm") or [""])[0] != name:
                    raise ControlError(
                        "confirmation_required",
                        "force resume requires the exact tunnel name",
                        status=409,
                    )
                result = get_control_service().resume(name, force=force)
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/ownership/handoff":
            try:
                result = get_control_service().handoff(
                    name, reason=(form.get("reason") or [""])[0]
                )
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200, json.dumps(result.as_dict()), "application/json; charset=utf-8"
            )
            return
        if parsed.path == "/api/trigger-auto":
            try:
                result = _switch_trigger_auto(name)
            except SystemExit as exc:
                self._send(409, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps(result), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/skill-import":
            try:
                imported = skillmgr.import_skill((form.get("src") or [""])[0])
            except SystemExit as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(
                200,
                json.dumps({"ok": True, "name": imported}),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/skill-enable":
            try:
                skillmgr.set_enabled(
                    (form.get("name") or [""])[0],
                    (form.get("who") or ["trigger"])[0],
                    (form.get("on") or ["1"])[0] != "0",
                )
            except SystemExit as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/skill-teach":
            try:
                from . import tmux as tmux_send
                from .cli import _resolve

                dtname = (form.get("dt") or [""])[0]
                sk = (form.get("skill") or [""])[0]
                data = _resolve(dtname)
                msg = skillmgr.teach(data["name"], [sk])
                tmux_send.send_keys(data["run"], msg)
            except SystemExit as exc:
                self._send(400, str(exc), "text/plain; charset=utf-8")
                return
            self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/skill-used":
            skillmgr.log_use(
                (form.get("dt") or [""])[0],
                (form.get("name") or [""])[0],
                (form.get("ok") or ["1"])[0] != "0",
                (form.get("detail") or [""])[0],
            )
            self._send(200, json.dumps({"ok": True}), "application/json; charset=utf-8")
            return
        if parsed.path == "/api/model":
            side = (form.get("side") or ["op"])[0]
            model = (form.get("model") or [""])[0]
            which = ["trigger"] if side == "op" else ["bullet"]
            try:
                data = get_control_service().model(name, model, which).data
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            info = data.get("trigger") if side == "op" else data.get("bullet")
            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "model": (info or {}).get("model") or model,
                        "trigger_model": (data.get("trigger") or {}).get("model") or "",
                        "bullet_model": (data.get("bullet") or {}).get("model") or "",
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path == "/api/freeze":
            sides = []
            side = (form.get("side") or ["both"])[0]
            if side in {"both", "trigger", "op"}:
                sides.append("trigger")
            if side in {"both", "bullet", "run"}:
                sides.append("bullet")
            try:
                data = (
                    get_control_service()
                    .freeze(name, sides, (form.get("tool") or ["auto"])[0])
                    .data
                )
            except ControlError as exc:
                self._send(
                    exc.status,
                    json.dumps(exc.as_dict()),
                    "application/json; charset=utf-8",
                )
                return
            self._send(
                200,
                json.dumps(
                    {
                        "ok": True,
                        "dst": oc_ops.is_dst(data),
                        "trigger_model": (data.get("trigger") or {}).get("model") or "",
                        "bullet_model": (data.get("bullet") or {}).get("model") or "",
                    }
                ),
                "application/json; charset=utf-8",
            )
            return
        service = get_control_service()
        try:
            if parsed.path == "/api/tunnel/create":
                result = service.create_tunnel(
                    (form.get("name") or [""])[0],
                    server=(form.get("server") or [""])[0],
                    container=(form.get("container") or [""])[0],
                    directory=(form.get("directory") or [""])[0],
                    trigger_tool=(form.get("trigger_tool") or ["opencode"])[0],
                    bullet_tool=(form.get("bullet_tool") or ["opencode"])[0],
                    local=(form.get("local") or ["0"])[0] == "1",
                )
            elif parsed.path == "/api/tunnel/remove":
                result = service.remove_tunnel(
                    name,
                    confirm=(form.get("confirm") or [""])[0],
                    kill=(form.get("kill") or ["0"])[0] == "1",
                )
            elif parsed.path == "/api/tunnel/reconnect":
                result = service.reconnect(name)
            elif parsed.path == "/api/tunnel/drop":
                result = service.drop(name, confirm=(form.get("confirm") or [""])[0])
            elif parsed.path in {"/api/hub/push", "/api/hub/pull"}:
                result = service.hub_sync(parsed.path.rsplit("/", 1)[-1])
            elif parsed.path == "/api/config/switch":
                result = service.switch_mode(
                    mode=(form.get("mode") or [""])[0],
                    client=(form.get("client") or [""])[0],
                    workspace=(form.get("workspace") or [""])[0],
                    server=(form.get("server") or [""])[0],
                    user=(form.get("user") or [""])[0],
                    confirm=(form.get("confirm") or [""])[0],
                )
            elif parsed.path == "/api/health/probe":
                result = service.probe_health(name)
            elif parsed.path == "/api/health/recover":
                result = service.recover(
                    name,
                    force=(form.get("force") or ["0"])[0] == "1",
                    confirm=(form.get("confirm") or [""])[0],
                )
            elif parsed.path == "/api/health/auto":
                result = service.set_auto_recover(
                    name, (form.get("enabled") or ["0"])[0] == "1"
                )
            else:
                result = None
        except ControlError as exc:
            self._send(
                exc.status,
                json.dumps(exc.as_dict()),
                "application/json; charset=utf-8",
            )
            return
        if result is not None:
            self._send(
                200,
                json.dumps(result.as_dict()),
                "application/json; charset=utf-8",
            )
            return
        if parsed.path != "/send":
            self._send(404, "not found")
            return
        side = (form.get("side") or ["op"])[0]
        text = (form.get("text") or [""])[0]
        try:
            result = get_control_service().send(name, text, side)
            pane = result.data["pane"]
        except ControlError as exc:
            self._send(
                exc.status, json.dumps(exc.as_dict()), "application/json; charset=utf-8"
            )
            return
        accept = self.headers.get("Accept") or ""
        if "application/json" in accept or self.headers.get("X-Requested-With"):
            self._send(
                200,
                json.dumps({"ok": True, "pane": pane}),
                "application/json; charset=utf-8",
            )
            return
        self.send_response(303)
        self.send_header("Location", f"/tunnels?t={normalize_dt(name)}")
        self.end_headers()


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except (OSError, webbrowser.Error):
        # The URL is already printed; headless and restricted environments may not have a browser.
        pass


def serve(
    host: str = HOST, port: int = DEFAULT_PORT, open_browser: bool = True
) -> None:
    with WebHTTPServer((host, port), Handler) as httpd:
        url = f"http://{host}:{port}"
        print(f"dt web  {url}  (Ctrl-C stop)")
        if open_browser:
            opener = threading.Timer(0.15, _open_browser, args=(url,))
            opener.daemon = True
            opener.start()
        httpd.serve_forever()
