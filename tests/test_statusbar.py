import json
from pathlib import Path

from dual_tmux import statusbar


def _home(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "dt-home"
    monkeypatch.setenv("DUAL_TMUX_HOME", str(home))
    return home


def test_state_roundtrip(monkeypatch, tmp_path: Path):
    home = _home(monkeypatch, tmp_path)
    statusbar.write_state(True, "tom7r:/root/andy/dual-tmux")
    state = statusbar.read_state()
    assert state["ok"] is True
    assert "tom7r" in state["detail"]
    assert state["ts"]
    assert (
        json.loads((home / "hub-sync.json").read_text(encoding="utf-8"))["ok"] is True
    )


def test_read_state_missing_or_corrupt(monkeypatch, tmp_path: Path):
    home = _home(monkeypatch, tmp_path)
    assert statusbar.read_state() == {}
    home.mkdir(parents=True)
    (home / "hub-sync.json").write_text("not-json", encoding="utf-8")
    assert statusbar.read_state() == {}


def test_chip_renders_states():
    ok = statusbar.chip("dt-msg", {"ok": True, "ts": "2026-09-02T10:01:02+08:00"})
    assert "dt:msg" in ok and "已同步" in ok and "10:01" in ok and "green" in ok
    fail = statusbar.chip("dt-msg", {"ok": False, "ts": "2026-09-02T10:02:03+08:00"})
    assert "同步失败" in fail and "10:02" in fail and "red" in fail
    local = statusbar.chip("dt-msg", None)
    assert "local" in local and "yellow" in local


def test_chip_syncing_shows_spinner_and_animates():
    a = statusbar.chip("dt-msg", {"ok": True}, syncing=True, frame=0)
    b = statusbar.chip("dt-msg", {"ok": True}, syncing=True, frame=1)
    assert "同步中" in a and "yellow" in a
    assert statusbar.SPINNER[0] in a
    assert "同步中" in b and statusbar.SPINNER[1] in b
    assert a != b


def test_busy_detects_persist_lock_dirs(monkeypatch, tmp_path: Path):
    home = _home(monkeypatch, tmp_path)
    assert statusbar.busy() is False
    (home / "locks" / "persist-tmux").mkdir(parents=True)
    assert statusbar.busy() is True


def test_signature_tracks_state_and_busy(monkeypatch, tmp_path: Path):
    home = _home(monkeypatch, tmp_path)
    statusbar.write_state(True, "dest")
    sig1 = statusbar.signature(True)
    assert sig1[0] == "hub" and sig1[2] is True
    assert statusbar.signature(True) == sig1
    (home / "locks" / "persist-opencode").mkdir(parents=True)
    assert statusbar.signature(True) != sig1
    assert statusbar.signature(False)[0] == "local"


class FakeTmux:
    def __init__(self, sessions, global_right="#H %H:%M"):
        self.sessions = set(sessions)
        self.global_right = global_right
        self.session_opts = {}
        self.set_calls = []

    def run(self, cmd, **kwargs):
        class R:
            def __init__(self, rc=0, out=""):
                self.returncode = rc
                self.stdout = out
                self.stderr = ""

        if cmd[:2] == ["tmux", "has-session"]:
            return R(0 if cmd[-1] in self.sessions else 1)
        if cmd[:2] == ["tmux", "show-option"]:
            opt = cmd[-1]
            if "-g" in cmd:
                return R(0, self.global_right + "\n")
            sess = cmd[cmd.index("-t") + 1]
            if opt == statusbar.MARKER:
                val = self.session_opts.get((sess, opt), "")
                return R(0 if val else 1, val + "\n" if val else "")
            val = self.session_opts.get((sess, opt), self.global_right)
            return R(0, val + "\n")
        if cmd[:2] == ["tmux", "set-option"]:
            sess = cmd[cmd.index("-t") + 1]
            self.set_calls.append(cmd)
            self.session_opts[(sess, cmd[-2])] = cmd[-1]
            return R()
        raise AssertionError(f"unexpected cmd: {cmd}")


def _patch(monkeypatch, fake: FakeTmux):
    monkeypatch.setattr(statusbar.subprocess, "run", fake.run)
    monkeypatch.setattr(
        statusbar.tmux_ops, "has_session", lambda name: name in fake.sessions
    )
    monkeypatch.setattr(statusbar.tmux_ops, "have_tmux", lambda: True)


def test_apply_sets_chip_and_marker(monkeypatch, tmp_path: Path):
    _home(monkeypatch, tmp_path)
    fake = FakeTmux(["op_x"])
    _patch(monkeypatch, fake)
    assert statusbar.apply(
        "op_x", "dt-x", {"ok": True, "ts": "2026-09-02T10:01:00+08:00"}
    )
    right = fake.session_opts[("op_x", "status-right")]
    assert "dt:x" in right and "已同步" in right
    assert fake.global_right in right
    assert fake.session_opts[("op_x", statusbar.MARKER)] == "1"


def test_apply_skips_missing_session(monkeypatch, tmp_path: Path):
    _home(monkeypatch, tmp_path)
    fake = FakeTmux([])
    _patch(monkeypatch, fake)
    assert not statusbar.apply("op_gone", "dt-gone", {"ok": True})
    assert fake.set_calls == []


def test_apply_preserves_user_custom_status_right(monkeypatch, tmp_path: Path):
    _home(monkeypatch, tmp_path)
    fake = FakeTmux(["op_x"])
    fake.session_opts[("op_x", "status-right")] = "#[fg=blue]my own bar"
    _patch(monkeypatch, fake)
    assert not statusbar.apply("op_x", "dt-x", {"ok": True})
    assert fake.session_opts[("op_x", "status-right")] == "#[fg=blue]my own bar"


def test_apply_skips_rewrite_when_unchanged(monkeypatch, tmp_path: Path):
    _home(monkeypatch, tmp_path)
    fake = FakeTmux(["op_x"])
    _patch(monkeypatch, fake)
    state = {"ok": True, "ts": "2026-09-02T10:01:00+08:00"}
    assert statusbar.apply("op_x", "dt-x", state)
    writes = len(fake.set_calls)
    assert statusbar.apply("op_x", "dt-x", state)
    assert len(fake.set_calls) == writes


def test_refresh_marks_syncing_while_busy(monkeypatch, tmp_path: Path):
    home = _home(monkeypatch, tmp_path)
    statusbar.write_state(True, "dest")
    (home / "locks" / "persist-tmux").mkdir(parents=True)
    fake = FakeTmux(["op_a"])
    _patch(monkeypatch, fake)
    statusbar.refresh([{"name": "dt-a", "op": "op_a", "run": ""}], hub_enabled=True)
    right = fake.session_opts[("op_a", "status-right")]
    assert "同步中" in right and "yellow" in right


def test_apply_overrides_own_previous_chip(monkeypatch, tmp_path: Path):
    _home(monkeypatch, tmp_path)
    fake = FakeTmux(["op_x"])
    _patch(monkeypatch, fake)
    statusbar.apply("op_x", "dt-x", {"ok": True, "ts": "2026-09-02T10:01:00+08:00"})
    assert statusbar.apply(
        "op_x", "dt-x", {"ok": False, "ts": "2026-09-02T10:02:00+08:00"}
    )
    right = fake.session_opts[("op_x", "status-right")]
    assert "同步失败" in right and right.count("dt:x") == 1


def test_refresh_local_mode_and_count(monkeypatch, tmp_path: Path):
    _home(monkeypatch, tmp_path)
    fake = FakeTmux(["op_a", "run_a"])
    _patch(monkeypatch, fake)
    tunnels = [
        {"name": "dt-a", "op": "op_a", "run": "run_a"},
        {"name": "dt-b", "op": "op_b", "run": ""},
    ]
    n = statusbar.refresh(tunnels, hub_enabled=False)
    assert n == 2
    assert "local" in fake.session_opts[("op_a", "status-right")]
    assert ("op_b", "status-right") not in fake.session_opts
