from dual_tmux.web import _page, _pane_name, _tunnels
from dual_tmux.store import save, tunnels_dir
from dual_tmux.config import AppConfig, write_config


def test_pane_name():
    data = {"op": "op_msg", "run": "run_msg"}
    assert _pane_name(data, "op") == "op_msg"
    assert _pane_name(data, "run") == "run_msg"


def test_page_lists_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    save(
        tunnels_dir() / "dt-msg.json",
        {"name": "dt-msg", "op": "op_msg", "run": "run_msg", "trigger": {}, "bullet": {}},
    )
    html = _page("dt-msg", "run")
    assert "dt-msg" in html
    assert "run / bullet" in html
    assert "/send" in html
    names = [r["name"] for r in _tunnels()]
    assert names == ["dt-msg"]
