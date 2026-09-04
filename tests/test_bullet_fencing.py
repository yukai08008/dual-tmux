import subprocess

from dual_tmux import recovery
from dual_tmux.cli import _fence_remote_bullet, _pane_shows_agent


def _data(sid="ses_fb37c74b8ffe9VH0RIKOSZfQJW"):
    return {
        "name": "dt-x",
        "bullet": {"tool": "opencode", "session_id": sid},
        "runtime": {
            "server": "root@106.75.97.247",
            "ssh_port": 24500,
            "container": "me_andy_browser",
        },
    }


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def test_remote_session_pids_parses_and_brackets_pattern():
    seen = []

    def runner(argv, **kwargs):
        seen.append(argv)
        return R(0, "101\n102\n")

    pids = recovery.remote_session_pids(_data(), runner=runner)
    assert pids == [101, 102]
    command = seen[0][-1]
    assert "[s]es_fb37c74b8ffe9VH0RIKOSZfQJW" in command
    assert "docker exec" in command and "me_andy_browser" in command


def test_remote_session_pids_none_without_server_or_sid():
    assert recovery.remote_session_pids(_data(""), runner=lambda *a, **k: R()) is None
    data = _data()
    data["runtime"] = {}
    assert recovery.remote_session_pids(data, runner=lambda *a, **k: R()) is None


def test_remote_session_pids_none_on_ssh_failure():
    def runner(argv, **kwargs):
        return R(255, "", "ssh failed")

    assert recovery.remote_session_pids(_data(), runner=runner) is None


def test_remote_session_pids_none_on_timeout():
    def runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=12)

    assert recovery.remote_session_pids(_data(), runner=runner) is None


def test_fence_kills_listed_pids():
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv[-1])
        if "pgrep" in argv[-1] and "kill" not in argv[-1]:
            return R(0, "101\n102\n")
        return R(0, "")

    killed = recovery.fence_remote_bullet(_data(), runner=runner)
    assert killed == [101, 102]
    kill_cmd = [c for c in calls if "kill 101 102" in c]
    assert kill_cmd, calls
    assert "kill -9" in kill_cmd[0]


def test_fence_noop_when_nothing_running():
    killed = recovery.fence_remote_bullet(_data(), runner=lambda *a, **k: R(0, ""))
    assert killed == []


def test_fence_none_when_check_fails():
    killed = recovery.fence_remote_bullet(_data(), runner=lambda *a, **k: R(255))
    assert killed is None


def test_pane_shows_agent_detects_tui(monkeypatch):
    from dual_tmux import tmux as tmux_ops

    tui = "  ▣ Build auto · Grok 4.6\n ⬝⬝ esc interrupt   220.5K  ctrl+p commands"
    monkeypatch.setattr(tmux_ops, "capture_pane", lambda name, start=-200: tui)
    assert _pane_shows_agent("run_x") is True
    shell = "root@box:~/intro_v2$ "
    monkeypatch.setattr(tmux_ops, "capture_pane", lambda name, start=-200: shell)
    assert _pane_shows_agent("run_x") is False


def test_fence_skip_when_tui_attached(monkeypatch):
    monkeypatch.setattr("dual_tmux.cli._pane_shows_agent", lambda name: True)
    called = []
    monkeypatch.setattr(
        recovery, "fence_remote_bullet", lambda data: called.append(data) or []
    )
    assert _fence_remote_bullet(_data(), _data()["bullet"], "run_x") is True
    assert called == []


def test_fence_refuses_blind_start_when_check_fails(monkeypatch):
    monkeypatch.setattr("dual_tmux.cli._pane_shows_agent", lambda name: False)
    monkeypatch.setattr(recovery, "fence_remote_bullet", lambda data: None)
    assert _fence_remote_bullet(_data(), _data()["bullet"], "run_x") is True


def test_fence_proceeds_after_killing_orphans(monkeypatch):
    monkeypatch.setattr("dual_tmux.cli._pane_shows_agent", lambda name: False)
    monkeypatch.setattr(recovery, "fence_remote_bullet", lambda data: [101])
    assert _fence_remote_bullet(_data(), _data()["bullet"], "run_x") is False


def test_fence_skipped_for_local_bullet():
    data = _data()
    data["runtime"] = {}
    assert _fence_remote_bullet(data, data["bullet"], "run_x") is False
