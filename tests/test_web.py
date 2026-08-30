import pytest

from dual_tmux.web import (
    _open_browser,
    _is_client_disconnect,
    _load_web_state,
    _opencode_auto,
    _pane_name,
    _resume_tunnel,
    _save_web_state,
    _switch_trigger_auto,
    _tunnels,
    dashboard_page,
    guide_page,
    skills_page,
    tunnels_page,
)
from dual_tmux.store import save, tunnels_dir
from dual_tmux.config import AppConfig, write_config


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
    monkeypatch.setattr("dual_tmux.web.webbrowser.open", lambda url, new=0: calls.append((url, new)))
    _open_browser("http://127.0.0.1:8787")
    assert calls == [("http://127.0.0.1:8787", 2)]


def test_admin_tabs_and_search(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    save(
        tunnels_dir() / "dt-msg.json",
        {"name": "dt-msg", "op": "op_msg", "run": "run_msg", "trigger": {}, "bullet": {}},
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
    assert 'lamp gray' in page
    assert "addBubble" in page
    assert "summarize" in page
    assert "pollspin" in page
    assert "op_parsed" in page or "addBubble" in page
    assert "dt-msg" in page
    assert "btabs" in page
    assert "tabadd" in page
    assert "closeTab" in page
    assert "btn-freeze" in page
    assert "m-op" in page
    assert "/api/model" in page
    assert "/api/models" in page
    assert "bindModelPicker" in page
    assert "会话同步" in page
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
    names = [r["name"] for r in _tunnels()]
    assert names == ["dt-msg"]
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
    assert 'href="/guide"' in guide
    assert 'rel="icon"' in guide


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
                    {"kind": "ask", "text": "继续上次任务", "extra": {"ts": "2026-08-29T11:00:00+08:00"}},
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
    monkeypatch.setattr(web.tmux_ops, "quit_opencode", lambda pane: calls.append(("quit", pane)) or True)
    monkeypatch.setattr(web.tmux_ops, "start_opencode", lambda pane, cmd: calls.append(("start", pane, cmd)))

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
        {"name": "dt-msg", "op": "op_msg", "run": "run_msg", "trigger": {}, "bullet": {}},
    )
    monkeypatch.setattr("dual_tmux.web.tmux_ops.has_session", lambda _: True)
    with pytest.raises(SystemExit, match="no frozen session id"):
        _switch_trigger_auto("dt-msg")
