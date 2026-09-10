from dual_tmux import activity


def test_semantic_fingerprint_ignores_spinner_footer_token_and_clock():
    first = """Useful answer\n▣  Build · grok-4.6\n■■■⬝⬝  esc interrupt\n2026-08-31 13:58:10\nThought: 106ms"""
    second = """Useful answer\n▣  Build · grok-4.6\n■■■■⬝  esc interrupt\n2026-08-31 13:59:22\nThought: 900ms"""
    assert activity.semantic_fingerprint(first) == activity.semantic_fingerprint(second)


def test_activity_evidence_tracks_real_change_and_stall(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    monkeypatch.setattr(activity.tmux_ops, "pane_command", lambda _pane: "opencode")
    monkeypatch.setattr(activity.tmux_ops, "has_session", lambda _pane: True)
    monkeypatch.setattr(activity.tmux_ops, "attached_clients", lambda _pane: 0)
    monkeypatch.setattr("dual_tmux.ownership.probe_writers", lambda *_args: {"status": "ok", "count": 1, "pids": [1], "reason": ""})
    data = {"name": "dt-a", "op": "op_a", "run": "run_a"}

    first = activity.activity_evidence(data, now=100, capture=lambda _pane: "answer one")
    same = activity.activity_evidence(data, now=200, capture=lambda _pane: "answer one\nThought: 2s")
    stalled = activity.activity_evidence(data, now=701, capture=lambda _pane: "answer one\n■■⬝")
    changed = activity.activity_evidence(data, now=702, capture=lambda _pane: "answer two")

    assert first["sides"]["trigger"]["last_semantic_change_at"] == 100
    assert same["sides"]["trigger"]["last_semantic_change_at"] == 100
    assert stalled["sides"]["trigger"]["state"] == "stalled"
    assert stalled["sides"]["trigger"]["sample_count"] == 3
    assert stalled["sides"]["trigger"]["window_seconds"] == 601
    assert changed["sides"]["trigger"]["state"] == "working"
    assert changed["sides"]["trigger"]["last_semantic_change_at"] == 702



def test_fingerprint_is_trigger_pane_only(monkeypatch):
    captured = []

    def capture(name, start=-200):
        captured.append((name, start))
        return "\x1b[31mhello\x1b[0m\nworld\n"

    monkeypatch.setattr(activity.tmux_ops, "capture_pane", capture)
    data = {"name": "dt-a", "op": "op_a", "run": "run_a"}
    first = activity.fingerprint(data)
    second = activity.fingerprint(data)
    assert first == second
    assert captured == [("op_a", -20), ("op_a", -20)]
    assert "run_a" not in [name for name, _start in captured]


def test_append_sample_skips_unchanged_fingerprint_and_mirrors_persist(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "dt"))
    persist = tmp_path / "sessions" / "opencode"
    monkeypatch.setenv("OPENCODE_SESSIONS", str(persist))
    monkeypatch.setattr(activity, "_tick_tenant", lambda: "tm_here")
    monkeypatch.setattr(activity.tmux_ops, "capture_pane", lambda *_a, **_k: "same pane")
    monkeypatch.setattr(activity.tmux_ops, "pane_command", lambda _pane: "opencode")
    data = {"name": "dt-a", "op": "op_a", "run": "run_a"}

    first = activity.append_sample(data)
    second = activity.append_sample(data)
    ticks = activity.ticks_path(data)
    mirrored = persist / "tm_here" / "ticks" / "op_a.log"
    assert ticks.is_file()
    assert mirrored.is_file()
    assert ticks.read_text(encoding="utf-8").count("\n") == 1
    assert second.split()[-1] == first.split()[-1]
    assert mirrored.read_text(encoding="utf-8") == ticks.read_text(encoding="utf-8")


def test_preferred_source_uses_newest_tick(tmp_path):
    root = tmp_path / "opencode"
    home = root / "tm_home" / "ticks"
    other = root / "tm_other" / "ticks"
    home.mkdir(parents=True)
    other.mkdir(parents=True)
    (home / "op_a.log").write_text(
        "100 2026-09-10T00:00:00 dt-a opencode ssh aaa\n", encoding="utf-8"
    )
    (other / "op_a.log").write_text(
        "200 2026-09-10T00:01:00 dt-a opencode ssh bbb\n", encoding="utf-8"
    )
    data = {"name": "dt-a", "op": "op_a"}
    assert activity.preferred_source(data, local="tm_home", root=root) == "tm_other"
    (home / "op_a.log").write_text(
        "200 2026-09-10T00:01:00 dt-a opencode ssh bbb\n", encoding="utf-8"
    )
    assert activity.preferred_source(data, local="tm_home", root=root) == "tm_home"
