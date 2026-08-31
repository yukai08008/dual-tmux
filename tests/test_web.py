import json
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from dual_tmux.config import AppConfig, write_config
from dual_tmux.recovery import read_state, save_state
from dual_tmux.store import save, tunnels_dir
from dual_tmux.web import (
    Handler,
    WebHTTPServer,
    _is_client_disconnect,
    _load_web_state,
    _open_browser,
    _opencode_auto,
    _pane_name,
    _resume_tunnel,
    _save_web_state,
    _switch_trigger_auto,
    _tunnels,
    dashboard_page,
    doctor_page,
    events_page,
    feishu_page,
    guide_page,
    memory_page,
    skills_page,
    tunnels_page,
)


def test_pane_name():
    data = {"op": "op_msg", "run": "run_msg"}
    assert _pane_name(data, "op") == "op_msg"
    assert _pane_name(data, "run") == "run_msg"


def test_opencode_auto_footer_detection():
    assert _opencode_auto("┃ Build auto · Grok 4.6") is True
    assert _opencode_auto("┃ Build · Grok 4.6") is False
    assert _opencode_auto("Build auto · old\nBuild · current") is False
    assert _opencode_auto("Build · old\nBuild auto · current") is True


def test_expected_browser_disconnect_errors_are_quiet():
    assert _is_client_disconnect(OSError(9, "Bad file descriptor")) is True
    assert _is_client_disconnect(BrokenPipeError()) is True
    assert _is_client_disconnect(ConnectionResetError()) is True
    assert _is_client_disconnect(OSError(28, "No space left on device")) is False
    assert _is_client_disconnect(ValueError("application error")) is False


def test_open_browser_uses_new_tab(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dual_tmux.web.webbrowser.open", lambda url, new=0: calls.append((url, new))
    )
    _open_browser("http://127.0.0.1:8787")
    assert calls == [("http://127.0.0.1:8787", 2)]


def test_web_exposes_agent_capabilities_and_operation_catalog():
    server = WebHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = f"http://127.0.0.1:{server.server_port}"
        capabilities = json.load(urlopen(root + "/api/capabilities", timeout=3))
        operations = json.load(urlopen(root + "/api/operations", timeout=3))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert capabilities["ok"] is True
    assert [row["name"] for row in capabilities["data"]] == [
        "opencode",
        "codex",
        "claude",
    ]
    assert any(row["name"] == "pane.send" for row in operations["data"])
    assert any(row["name"] == "tunnel.create" for row in operations["data"])
    assert any(row["name"] == "health.recover" for row in operations["data"])


def test_web_control_endpoints_delegate_and_return_structured_results(monkeypatch):
    from dual_tmux.control import ControlResult

    service = type(
        "Service",
        (),
        {
            "create_tunnel": lambda self, name, **kwargs: ControlResult(
                "tunnel.create", {"name": name, **kwargs}, "audit.create"
            ),
            "probe_health": lambda self, name: ControlResult(
                "health.probe", {"name": name, "healthy": True}, "audit.health"
            ),
        },
    )()
    monkeypatch.setattr("dual_tmux.web.get_control_service", lambda: service)
    server = WebHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(path, fields):
        body = urlencode(fields).encode()
        request = Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return json.load(urlopen(request, timeout=3))

    try:
        created = post(
            "/api/tunnel/create",
            {
                "name": "web-smoke",
                "directory": "/tmp",
                "trigger_tool": "codex",
                "bullet_tool": "claude",
            },
        )
        health = post("/api/health/probe", {"t": "web-smoke"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert created["operation"] == "tunnel.create"
    assert created["data"]["trigger_tool"] == "codex"
    assert health["operation"] == "health.probe"
    assert health["data"]["healthy"] is True


def test_web_config_get_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", workspace="/tmp"))
    before = (tmp_path / "config.toml").read_bytes()
    server = WebHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.load(
            urlopen(f"http://127.0.0.1:{server.server_port}/api/config", timeout=3)
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert payload["mode"] == "local"
    assert payload["client"] == "tm_box"
    assert (tmp_path / "config.toml").read_bytes() == before


def test_web_rejects_cross_origin_writes():
    server = WebHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = Request(
        f"http://127.0.0.1:{server.server_port}/api/health/probe",
        data=urlencode({"t": "dt-msg"}).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://evil.example",
        },
    )
    try:
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert caught.value.code == 403
    assert payload["error"]["code"] == "origin_rejected"


def test_feishu_page_and_local_pair_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", workspace="/tmp"))
    page = feishu_page()
    assert "扫码绑定" in page
    assert "/api/feishu/pair" in page
    assert "/api/feishu/poll" in page
    assert "不需要 App ID、App Secret 或公网 callback" in page
    assert "/api/feishu/configure" not in page
    from dual_tmux.feishu import AppRegistrationService

    monkeypatch.setattr(
        AppRegistrationService,
        "begin",
        lambda self: {
            "authorization_url": "https://accounts.feishu.cn/device?code=abc",
            "expires_in": 600,
            "status": "pending",
        },
    )
    monkeypatch.setattr(
        AppRegistrationService, "poll", lambda self: {"status": "pending"}
    )
    server = WebHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"

    def post(path, payload):
        request = Request(
            root + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        return json.load(urlopen(request, timeout=3))

    try:
        paired = post("/api/feishu/pair", {})
        polled = post("/api/feishu/poll", {})
        status = json.load(urlopen(root + "/api/feishu/status", timeout=3))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert paired["qr"].startswith("data:image/svg+xml")
    assert "accounts.feishu.cn" in paired["authorization_url"]
    assert polled["status"] == "pending"
    assert status["configured"] is False


def test_feishu_pair_rejects_any_manual_app_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", workspace="/tmp"))
    server = WebHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = Request(
        f"http://127.0.0.1:{server.server_port}/api/feishu/pair",
        data=json.dumps(
            {"app_id": "cli_app", "redirect_uri": "https://hub/callback", "app_secret": "must-not-pass"}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with pytest.raises(HTTPError) as caught:
            urlopen(request, timeout=3)
        payload = json.loads(caught.value.read())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert caught.value.code == 400
    assert payload["error"]["code"] == "invalid_request"


def test_health_endpoint_reads_cache_without_probing(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box"))
    save(
        tunnels_dir() / "dt-msg.json",
        {"name": "dt-msg", "op": "op_msg", "run": "run_msg"},
    )
    state = read_state("dt-msg")
    state["status"] = "attention"
    save_state(state)
    server = WebHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.load(
            urlopen(
                f"http://127.0.0.1:{server.server_port}/api/health?t=dt-msg", timeout=3
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert payload["status"] == "attention"


def test_admin_tabs_and_search(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    save(
        tunnels_dir() / "dt-msg.json",
        {
            "name": "dt-msg",
            "op": "op_msg",
            "run": "run_msg",
            "trigger": {
                "agent_client": {
                    "name": "codex",
                    "version": "0.151.0",
                    "location": "local",
                }
            },
            "bullet": {
                "agent_client": {
                    "name": "claude",
                    "version": "2.1.191",
                    "location": "docker",
                }
            },
        },
    )
    dash = dashboard_page()
    assert "Dashboard" in dash
    assert 'href="/tunnels"' in dash
    assert "dt-msg" in dash
    page = tunnels_page("")
    assert "选择隧道" in page
    assert "发给 trigger" in page
    assert "轮询状态" in page
    assert page.index("trigger 问答") < page.index("发给 trigger")
    assert 'rows="10"' in page
    assert "bullet 会话" in page
    assert "logLine" in page
    assert "lamp-op" in page
    assert "trigger 问答" in page
    assert "setPollBusy" in page
    assert "lamp gray" in page
    assert "addBubble" in page
    assert "summarize" in page
    assert "pollspin" in page
    assert "op_parsed" in page or "addBubble" in page
    assert "dt-msg" in page
    assert "btabs" in page
    assert "tabadd" in page
    assert "closeTab" in page
    assert "btn-freeze" in page
    assert "createf" in page
    assert "/api/tunnel/create" in page
    assert "/api/tunnel/remove" in page
    assert "/api/tunnel/reconnect" in page
    assert "/api/tunnel/drop" in page
    assert "/api/health/probe" in page
    assert "/api/health/recover" in page
    assert "/api/health/auto" in page
    assert "/api/hub/push" in page
    assert "/api/hub/pull" in page
    assert "/api/config/switch" in page
    assert "new-trigger-tool" in page
    assert "new-bullet-tool" in page
    assert "j.trigger_tool !== 'opencode'" in page
    assert "j.bullet_tool !== 'opencode'" in page
    assert "m-op" in page
    assert "/api/model" in page
    assert "/api/models" in page
    assert "bindModelPicker" in page
    assert "会话同步" in page
    assert "trigger client" in page
    assert "bullet client" in page
    assert "healthbox" in page
    assert "/api/health" in Handler.do_GET.__code__.co_consts
    assert "trigger_client" in page
    assert "bullet_client" in page
    assert "syncbox" in page
    assert "localStorage" in page
    assert "restoreTabs" in page
    assert "TABS_KEY" in page
    assert "/api/resume" in page
    assert "ensureResumed" in page
    assert "refreshRows" in page
    assert "setInterval(refreshRows, 5000)" in page
    assert "fetch('/api/tunnels')" in page
    assert "/api/web-state" in page
    assert "最近访问" in page
    assert "visitHistory" in page
    assert "threadEl.scrollHeight-threadEl.scrollTop" in page
    assert "preserveThreadScroll" in page
    assert "WAIT_MAX_MS" in page
    assert "j.op_auto === false" in page
    assert "btn-auto-op" in page
    assert "/api/trigger-auto" in page
    rows = _tunnels()
    assert [r["name"] for r in rows] == ["dt-msg"]
    assert rows[0]["trigger_client"]["version"] == "0.151.0"
    assert rows[0]["bullet_client"]["location"] == "docker"
    assert rows[0]["health"]["status"] == "disabled"
    skills = skills_page()
    assert "Skills" in skills
    assert "btn-import" in skills
    assert "选择并预览" in skills
    assert "尚未上传" in skills
    assert "/api/skill-upload" in skills
    assert "renderTree" in skills
    assert "pick-dir" in skills
    assert "pick-file" in skills
    assert "hiddenPath" in skills
    assert 'data-dir=""' in skills
    assert "files selected" in skills
    assert "FormData" in skills
    assert "/api/skill-tree" in skills
    assert "/api/skill-installed-file" in skills
    assert "已安装内容" in skills
    guide = guide_page()
    assert "使用指南" in guide
    assert "创建完整 DST" in guide
    assert "dt make dst &lt;name&gt;" in guide
    assert "dt config --init --local" in guide
    assert "dt config --server myserver --user andy" in guide
    assert 'href="/guide"' in guide
    assert 'rel="icon"' in guide
    assert "/api/memory" in memory_page()
    assert "/api/events" in events_page()
    assert "/api/doctor/run" in doctor_page()
    assert 'href="/memory"' in page
    assert 'href="/events"' in page
    assert 'href="/doctor"' in page


def test_web_state_keeps_closed_tunnel_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    payload = {
        "open_tabs": ["dt-msg2"],
        "active": "dt-msg2",
        "history": {
            "dt-msg": {
                "firstVisitedAt": "2026-08-29T10:00:00+08:00",
                "lastVisitedAt": "2026-08-29T11:00:00+08:00",
                "visits": 3,
                "thread": [
                    {
                        "kind": "ask",
                        "text": "继续上次任务",
                        "extra": {"ts": "2026-08-29T11:00:00+08:00"},
                    },
                    {"kind": "ans", "text": "已经完成第一步", "extra": {"model": "m"}},
                ],
                "log": [{"kind": "done", "text": "本轮结束"}],
            },
            "dt-msg2": {"visits": 1, "thread": [], "log": []},
        },
    }
    saved = _save_web_state(payload)
    assert saved["open_tabs"] == ["dt-msg2"]
    assert "dt-msg" in saved["history"]
    assert saved["history"]["dt-msg"]["thread"][1]["text"] == "已经完成第一步"
    loaded = _load_web_state()
    assert loaded == saved
    assert (tmp_path / "web-state.json").is_file()


def test_web_auto_resume_only_for_offline_dst(tmp_path, monkeypatch):
    from dual_tmux import cli, web

    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    data = {
        "name": "dt-msg",
        "op": "op_msg",
        "run": "run_msg",
        "trigger": {"tool": "opencode", "model": "m", "session_id": "op-1"},
        "bullet": {"tool": "opencode", "model": "m", "session_id": "run-1"},
    }
    save(tunnels_dir() / "dt-msg.json", data)
    live = {"value": False}
    monkeypatch.setattr(web.tmux_ops, "has_session", lambda _: live["value"])
    calls = []

    def fake_resume(name, force=False):
        calls.append((name, force))
        live["value"] = True
        return data

    monkeypatch.setattr(cli, "apply_resume", fake_resume)
    result = _resume_tunnel("dt-msg")
    assert result == {"ok": True, "resumed": True, "op_live": True, "run_live": True}
    assert calls == [("dt-msg", False)]
    assert _resume_tunnel("dt-msg")["resumed"] is False

    data["bullet"] = {}
    save(tunnels_dir() / "dt-msg.json", data)
    live["value"] = False
    with pytest.raises(SystemExit, match="requires a DST"):
        _resume_tunnel("dt-msg")


def test_web_switches_bound_trigger_to_auto(tmp_path, monkeypatch):
    from dual_tmux import web

    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    data = {
        "name": "dt-msg",
        "op": "op_msg",
        "run": "run_msg",
        "trigger": {"tool": "opencode", "session_id": "ses_trigger"},
        "bullet": {"tool": "opencode", "session_id": "ses_bullet"},
    }
    save(tunnels_dir() / "dt-msg.json", data)
    captures = iter(["Build · model", "Build auto · model"])
    calls = []
    monkeypatch.setattr(web, "_capture", lambda _: next(captures))
    monkeypatch.setattr(web.tmux_ops, "has_session", lambda _: True)
    monkeypatch.setattr(web.tmux_ops, "pane_command", lambda _: "opencode")
    monkeypatch.setattr(
        web.tmux_ops, "quit_opencode", lambda pane: calls.append(("quit", pane)) or True
    )
    monkeypatch.setattr(
        web.tmux_ops,
        "start_opencode",
        lambda pane, cmd: calls.append(("start", pane, cmd)),
    )

    result = _switch_trigger_auto("dt-msg")
    assert result == {"ok": True, "changed": True, "auto": True, "pane": "op_msg"}
    assert calls == [
        ("quit", "op_msg"),
        ("start", "op_msg", "opencode --auto -s ses_trigger"),
    ]


def test_web_trigger_auto_requires_frozen_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    save(
        tunnels_dir() / "dt-msg.json",
        {
            "name": "dt-msg",
            "op": "op_msg",
            "run": "run_msg",
            "trigger": {},
            "bullet": {},
        },
    )
    monkeypatch.setattr("dual_tmux.web.tmux_ops.has_session", lambda _: True)
    with pytest.raises(SystemExit, match="no frozen session id"):
        _switch_trigger_auto("dt-msg")
