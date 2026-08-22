from dual_tmux.web import _pane_name, _tunnels, dashboard_page, tunnels_page
from dual_tmux.store import save, tunnels_dir
from dual_tmux.config import AppConfig, write_config


def test_pane_name():
    data = {"op": "op_msg", "run": "run_msg"}
    assert _pane_name(data, "op") == "op_msg"
    assert _pane_name(data, "run") == "run_msg"


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
    names = [r["name"] for r in _tunnels()]
    assert names == ["dt-msg"]
