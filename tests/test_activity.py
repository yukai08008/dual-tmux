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

