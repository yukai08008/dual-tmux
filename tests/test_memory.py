from dual_tmux.config import AppConfig, write_config
from dual_tmux.opsdir import prepare
from dual_tmux.store import save, tunnels_dir
from dual_tmux import memory as mem


def _tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    save(
        tunnels_dir() / "dt-msg.json",
        {
            "name": "dt-msg",
            "op": "op_msg",
            "run": "run_msg",
            "runtime": {"server": "tom7r"},
            "trigger": {},
            "bullet": {},
        },
    )
    prepare(
        {
            "name": "dt-msg",
            "op": "op_msg",
            "run": "run_msg",
            "runtime": {"server": "tom7r"},
            "trigger": {"session_id": "ses_a"},
            "bullet": {"session_id": "ses_b"},
        }
    )


def test_shared_and_agent_json(tmp_path, monkeypatch):
    _tunnel(tmp_path, monkeypatch)
    mem.put_fact("server", "tom7r")
    shared = mem.get_memory()
    assert shared["facts"]["server"] == "tom7r"
    assert (tmp_path / "MEMORY.json").is_file()
    mem.put_fact("container", "box", "dt-msg")
    agent = mem.get_memory("dt-msg")
    assert agent["facts"]["container"] == "box"
    assert "container" not in shared["facts"]
    assert (tmp_path / "ops" / "op_msg" / "MEMORY.json").is_file()


def test_notes_day_and_fts(tmp_path, monkeypatch):
    _tunnel(tmp_path, monkeypatch)
    mem.add_note("dt-msg", "rebuild container on host", title="rebuild", kind="decision", day="2026-08-21")
    mem.add_note("dt-msg", "mermaid flow filed in docs", title="arch", kind="note", day="2026-08-22")
    day = mem.query_notes("dt-msg", day="2026-08-21")
    assert len(day) == 1
    assert "rebuild" in day[0]["body"]
    hits = mem.query_notes("dt-msg", q="mermaid")
    assert len(hits) == 1
    assert hits[0]["title"] == "arch"
    span = mem.query_notes("dt-msg", since="2026-08-21", until="2026-08-21")
    assert len(span) == 1
    assert (tmp_path / "ops" / "op_msg" / "memory.sqlite").is_file()


def test_agents_md_points_at_memory(tmp_path, monkeypatch):
    _tunnel(tmp_path, monkeypatch)
    text = (tmp_path / "ops" / "op_msg" / "AGENTS.md").read_text()
    assert "MEMORY.json" in text
    assert "memory.sqlite" in text
