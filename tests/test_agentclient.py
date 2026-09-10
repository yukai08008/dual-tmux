import subprocess

import pytest

from dual_tmux import agentclient, oc


@pytest.mark.parametrize(
    ("name", "raw", "version"),
    [
        ("opencode", "1.18.20\n", "1.18.20"),
        ("codex", "codex-cli 0.151.0\n", "0.151.0"),
        ("claude", "2.1.169 (Claude Code)\n", "2.1.169"),
    ],
)
def test_parse_version_output(name: str, raw: str, version: str):
    got, output = agentclient.parse_version_output(name, raw)
    assert got == version
    assert output == raw.strip()


def test_resolve_name_prefers_foreground_and_supports_aliases():
    assert agentclient.resolve_name("codex", "opencode") == "codex"
    assert agentclient.resolve_name("ssh", "claude-code") == "claude"
    assert agentclient.resolve_name("bash", "unknown") == ""
    assert (
        agentclient.detect_name(
            ["node /opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js"]
        )
        == "codex"
    )
    assert (
        agentclient.detect_name(["node /usr/local/lib/claude/claude.mjs --resume"])
        == "claude"
    )
    assert agentclient.detect_name(["ssh box", "bash -lc opencode"]) == "opencode"


def test_collect_local_records_path_and_version(monkeypatch):
    monkeypatch.setattr(
        "dual_tmux.agentclient.shutil.which", lambda name: f"/opt/bin/{name}"
    )
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, stdout="codex-cli 0.151.0\n", stderr=""
        )

    got = agentclient.collect_local("codex", runner=run)
    assert got["name"] == "codex"
    assert got["version"] == "0.151.0"
    assert got["executable"] == "/opt/bin/codex"
    assert got["location"] == "local"
    assert got["error"] == ""
    assert calls[0][0] == ["/opt/bin/codex", "--version"]


def test_collect_remote_ssh_parses_marker():
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                "Welcome to Ubuntu 24.04\n"
                "DT_AGENT_BIN=/usr/local/bin/opencode\n"
                "DT_AGENT_VERSION_BEGIN\n1.18.20\nDT_AGENT_VERSION_END\n"
            ),
            stderr="",
        )

    got = agentclient.collect_remote("opencode", ["ssh", "box"], host="box", runner=run)
    assert got["version"] == "1.18.20"
    assert got["executable"] == "/usr/local/bin/opencode"
    assert got["location"] == "ssh"
    assert calls[0][0][:2] == ["ssh", "box"]
    assert "command -v opencode" in calls[0][0][-1]


def test_collect_remote_docker_quotes_container():
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                "DT_AGENT_BIN=/usr/bin/claude\n"
                "DT_AGENT_VERSION_BEGIN\n2.1.169 (Claude Code)\nDT_AGENT_VERSION_END\n"
            ),
            stderr="",
        )

    got = agentclient.collect_remote(
        "claude",
        ["ssh", "box"],
        host="box",
        container="work box",
        runner=run,
    )
    assert got["name"] == "claude"
    assert got["version"] == "2.1.169"
    assert got["location"] == "docker"
    assert "docker exec 'work box'" in calls[0][-1]


def test_collect_rejects_non_whitelist_client():
    got = agentclient.collect_local("bash")
    assert got["name"] == ""
    assert "unsupported" in got["error"]


def test_remote_probe_falls_back_to_live_process_mount_namespace():
    script = agentclient._probe_script("opencode")
    assert "for x in /proc/[0-9]*/exe" in script
    assert 'candidate="${x%/exe}/root$target"' in script
    assert "p=$target; run=$candidate" in script


def test_active_remote_requires_live_process_and_parses_exact_session(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            "ses_live\tlive-slug\tLive\t/workspace\tprovider/model\tbuild\n",
            "",
        )

    monkeypatch.setattr(oc.subprocess, "run", run)
    session = oc.active_remote(["ssh", "box"])
    assert session and session.session_id == "ses_live"
    assert session.directory == "/workspace"
    assert "/proc/[0-9]*/cmdline" in calls[0][-1]
    assert "/proc/%s/root" in calls[0][-1]
    assert "pid+db" in calls[0][-1]
    assert "OPENCODE_DB" in calls[0][-1]


def test_active_remote_does_not_fall_back_to_latest(monkeypatch):
    monkeypatch.setattr(
        oc.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, "", ""),
    )
    assert oc.active_remote(["ssh", "box"]) is None


def test_active_remote_resolves_container_identity_from_process_cgroup(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                argv,
                0,
                "ses_live\tlive-slug\tLive\t/workspace\tprovider/model\tbuild\tdeadbeef1234\n",
                "",
            )
        return subprocess.CompletedProcess(argv, 0, "/work_box\n", "")

    monkeypatch.setattr(oc.subprocess, "run", run)
    session = oc.active_remote(["ssh", "box"])
    assert session and session.container == "work_box"
    assert "docker inspect" in calls[1][-1]


def test_active_remote_orders_by_process_start_and_ignores_child_sessions(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append(argv[-1])
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(oc.subprocess, "run", run)
    assert oc.active_remote(["ssh", "box"], "work") is None
    script = seen[0]
    assert "/proc/%s/stat" in script
    assert "key=lambda x:x[3]" in script
    assert "parent_id IS NULL" in script


def test_blank_local_tui_does_not_bind_session_older_than_process(monkeypatch):
    seen = []
    monkeypatch.setattr(oc, "_agent_process", lambda _pid: ("opencode --auto", 123_000))
    monkeypatch.setattr(
        oc,
        "by_directory",
        lambda cwd, created_after_ms=0: seen.append((cwd, created_after_ms)) or None,
    )
    assert oc.from_pane("10", "/workspace", fallback=True) is None
    assert seen == [("/workspace", 118_000)]


def test_elapsed_seconds_supports_long_lived_processes():
    assert oc._elapsed_seconds("01:02") == 62
    assert oc._elapsed_seconds("02:01:02") == 7262
    assert oc._elapsed_seconds("3-02:01:02") == 266462


def test_agent_process_reads_untruncated_command_separately_from_elapsed(monkeypatch):
    sid = "ses_f9a125dbdffelXmINuIVU0D7CT"
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        output = f"opencode --auto -s {sid}\n" if "command=" in argv else "22:47\n"
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr(oc.subprocess, "run", run)
    command, started_ms = oc._agent_process("24355")

    assert command == f"opencode --auto -s {sid}"
    assert started_ms > 0
    assert calls == [
        ["ps", "-ww", "-p", "24355", "-o", "command="],
        ["ps", "-p", "24355", "-o", "etime="],
    ]


def test_empty_side_is_backward_compatible_shape():
    from dual_tmux.oc import empty_side

    side = empty_side()
    assert side["tool"] == "opencode"
    assert side["agent_client"]["name"] == ""


def _point(kind: str = "local") -> dict:
    return {
        "kind": kind,
        "cwd": "/workspace",
        "cmd": "",
        "ssh": "box" if kind in {"ssh", "docker"} else "",
        "container": "work" if kind == "docker" else "",
        "directory": "/workspace",
        "resume_cmd": "",
        "hops": [],
        "seen_at": "",
    }


def test_freeze_opencode_keeps_session_and_client_metadata(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.oc import OcSession, empty_side

    data = {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": empty_side(),
        "bullet": empty_side(),
        "runtime": {},
    }
    monkeypatch.setattr(cli.wp, "discover", lambda _name: _point())
    monkeypatch.setattr(cli.wp, "walk_commands", lambda _pid: [])
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": "opencode", "cwd": "/workspace"},
    )
    monkeypatch.setattr(
        "dual_tmux.agentclient.collect",
        lambda *args, **kwargs: {
            **agentclient.empty(),
            "name": "opencode",
            "version": "1.18.20",
            "location": "local",
        },
    )
    monkeypatch.setattr(
        cli.oc_ops,
        "from_pane",
        lambda *args, **kwargs: OcSession("ses_1", "slug", model="provider/model"),
    )
    monkeypatch.setattr(cli.ev, "emit", lambda *args, **kwargs: None)
    assert cli._freeze_one(data, "trigger", "op_test", "auto", False)
    assert data["trigger"]["session_id"] == "ses_1"
    assert data["trigger"]["agent_client"]["version"] == "1.18.20"


@pytest.mark.parametrize("name", ["codex", "claude"])
def test_freeze_non_opencode_records_client_without_fake_session(
    monkeypatch, name: str
):
    from dual_tmux import cli
    from dual_tmux.oc import empty_side

    data = {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": empty_side(),
        "bullet": empty_side(),
        "runtime": {},
    }
    data["trigger"].update(session_id="ses_old", slug="old", model="old/model")
    monkeypatch.setattr(cli.wp, "discover", lambda _name: _point())
    monkeypatch.setattr(cli.wp, "walk_commands", lambda _pid: [])
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": name, "cwd": "/workspace"},
    )
    monkeypatch.setattr(
        "dual_tmux.agentclient.collect",
        lambda *args, **kwargs: {
            **agentclient.empty(),
            "name": name,
            "version": "1.2.3",
            "location": "local",
        },
    )
    monkeypatch.setattr(cli.ev, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "dual_tmux.agent_sessions.discover_local", lambda *args, **kwargs: None
    )

    assert cli._freeze_one(data, "trigger", "op_test", "auto", False) is False
    assert data["trigger"]["session_id"] == "ses_old"
    assert data["trigger"]["slug"] == "old"
    assert data["trigger"]["model"] == "old/model"


def test_freeze_remote_bullet_collects_inside_docker(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.oc import empty_side

    data = {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": empty_side(),
        "bullet": empty_side("claude"),
        "runtime": {"server": "box", "container": "work"},
    }
    seen = {}
    monkeypatch.setattr(cli.wp, "discover", lambda _name: _point("docker"))
    monkeypatch.setattr(cli.wp, "walk_commands", lambda _pid: [])
    monkeypatch.setattr(cli.wp, "apply_runtime", lambda *_args: None)
    monkeypatch.setattr(cli.wp, "remote_docker_exec_containers", lambda *_args: [])
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": "ssh", "cwd": "/workspace"},
    )
    monkeypatch.setattr(cli, "_ssh_argv", lambda _data: ["ssh", "box"])

    def collect(name, **kwargs):
        seen.update(name=name, **kwargs)
        return {
            **agentclient.empty(),
            "name": name,
            "version": "2.1.169",
            "location": kwargs["location"],
        }

    monkeypatch.setattr("dual_tmux.agentclient.collect", collect)
    monkeypatch.setattr(cli.ev, "emit", lambda *args, **kwargs: None)

    assert cli._freeze_one(data, "bullet", "run_test", "auto", False) is False
    assert seen["name"] == "claude"
    assert seen["location"] == "docker"
    assert seen["ssh_argv"] == ["ssh", "box"]
    assert seen["container"] == "work"


def test_freeze_disconnected_shell_does_not_bind_latest_or_mutate_runtime(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.oc import empty_side

    data = {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": empty_side(),
        "bullet": empty_side(),
        "runtime": {"server": "tom7r", "directory": "/workspace", "cmd": "ssh tom7r"},
    }
    monkeypatch.setattr(cli.wp, "discover", lambda _name: _point("ssh"))
    monkeypatch.setattr(cli.wp, "walk_commands", lambda _pid: [])
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": "zsh", "cwd": "/Users/andy"},
    )
    monkeypatch.setattr(
        "dual_tmux.agentclient.collect",
        lambda *a, **k: {**agentclient.empty(), "name": "opencode", "location": "ssh"},
    )
    monkeypatch.setattr(cli.oc_ops, "from_pane", lambda *a, **k: None)
    monkeypatch.setattr(
        cli.oc_ops,
        "active_remote",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not probe stale transport")
        ),
    )
    monkeypatch.setattr(cli.ev, "emit", lambda *a, **k: None)

    assert cli._freeze_one(data, "bullet", "run_test", "auto", False) is False
    assert data["bullet"]["session_id"] == ""
    assert data["runtime"] == {
        "server": "tom7r",
        "directory": "/workspace",
        "cmd": "ssh tom7r",
    }


def test_freeze_remote_probe_failure_does_not_commit_candidate_runtime(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.oc import empty_side

    original = {
        "server": "tom7r",
        "container": "old_box",
        "directory": "/old",
        "cmd": "ssh tom7r",
    }
    data = {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": empty_side(),
        "bullet": empty_side(),
        "runtime": dict(original),
        "run_point": {"kind": "ssh", "ssh": "tom7r"},
    }
    point = {
        **_point("docker"),
        "ssh": "root@10.88.0.20",
        "container": "cp_gateway_24629",
        "directory": "/workspace",
        "hops": [{"command": "docker exec -it cp_gateway_24629 bash"}],
    }
    monkeypatch.setattr(cli.wp, "discover", lambda _name: point)
    monkeypatch.setattr(cli.wp, "walk_commands", lambda _pid: ["ssh root@10.88.0.20"])
    monkeypatch.setattr(
        cli.wp, "remote_docker_exec_containers", lambda *_args: ["cp_gateway_24629"]
    )
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": "ssh", "cwd": "/Users/andy"},
    )
    monkeypatch.setattr(
        "dual_tmux.agentclient.collect",
        lambda *args, **kwargs: {
            **agentclient.empty(),
            "name": "opencode",
            "location": "docker",
            "error": "probe failed",
        },
    )
    monkeypatch.setattr(cli.oc_ops, "from_pane", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.oc_ops, "active_remote", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.ev, "emit", lambda *args, **kwargs: None)

    assert not cli._freeze_one(data, "bullet", "run_test", "auto", False)
    assert data["runtime"] == original
    assert data["run_point"] == {"kind": "ssh", "ssh": "tom7r"}


def test_freeze_commits_verified_live_runtime_and_session(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.oc import OcSession, empty_side

    data = {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": empty_side(),
        "bullet": empty_side(),
        "runtime": {"server": "tom7r", "container": "old_box", "directory": "/old"},
    }
    point = {
        **_point("docker"),
        "ssh": "root@10.88.0.20",
        "container": "old_box",
        "directory": "/workspace",
        "cwd": "/workspace",
        "hops": [{"command": "docker exec -it cp_gateway_24629 bash"}],
    }
    monkeypatch.setattr(cli.wp, "discover", lambda _name: point)
    monkeypatch.setattr(cli.wp, "walk_commands", lambda _pid: ["ssh root@10.88.0.20"])
    monkeypatch.setattr(
        cli.wp, "remote_docker_exec_containers", lambda *_args: ["cp_gateway_24629"]
    )
    monkeypatch.setattr(
        cli.tmux_ops,
        "pane_info",
        lambda _name: {"pid": "1", "cmd": "ssh", "cwd": "/Users/andy"},
    )
    monkeypatch.setattr(
        "dual_tmux.agentclient.collect",
        lambda *args, **kwargs: {
            **agentclient.empty(),
            "name": "opencode",
            "version": "1.18.29",
            "location": "docker",
        },
    )
    monkeypatch.setattr(cli.oc_ops, "from_pane", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli.oc_ops,
        "active_remote",
        lambda ssh, container: OcSession(
            "ses_remote", "quiet-fox", directory="/workspace"
        ),
    )
    monkeypatch.setattr(cli, "write_entry", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli.ev, "emit", lambda *args, **kwargs: None)

    assert cli._freeze_one(data, "bullet", "run_test", "auto", False)
    assert data["runtime"]["server"] == "root@10.88.0.20"
    assert data["runtime"]["container"] == "cp_gateway_24629"
    assert data["runtime"]["directory"] == "/workspace"
    assert "root@10.88.0.20" in data["runtime"]["cmd"]
    assert data["bullet"]["session_id"] == "ses_remote"
    assert data["run_point"]["ssh"] == "root@10.88.0.20"
    assert data["run_point"]["hops"] == []


def test_partial_freeze_is_saved_but_returns_failure(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.oc import empty_side

    data = {
        "name": "dt-test",
        "op": "op_test",
        "run": "run_test",
        "trigger": empty_side(),
        "bullet": empty_side(),
    }
    saved = []
    spans = []

    class Span:
        def ok(self, **fields):
            spans.append(("ok", fields))

        def fail(self, error, **fields):
            spans.append(("fail", error, fields))

    monkeypatch.setattr(cli, "_resolve", lambda _name: data)
    monkeypatch.setattr(cli, "find_dt", lambda _name: "/tmp/dt-test.json")
    monkeypatch.setattr(
        cli,
        "freeze_sides",
        lambda *_args, **_kwargs: {"trigger": True, "bullet": False},
    )
    monkeypatch.setattr(cli.wp, "stamp", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "save", lambda _path, value: saved.append(value.copy()))
    monkeypatch.setattr(cli.ev, "timed", lambda *_args, **_kwargs: Span())
    monkeypatch.setattr(cli.hub, "push_best_effort", lambda **_kwargs: None)

    with pytest.raises(SystemExit, match="freeze failed for bullet"):
        cli._apply_freeze_legacy("dt-test")

    assert saved
    assert spans[0][0] == "fail"
