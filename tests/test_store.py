import pytest

from dual_tmux.config import AppConfig, _parse_toml, init_config
from dual_tmux.identity import legal_source, legal_user, remote_sessions_root
from dual_tmux.runtime import build_cmd
from dual_tmux.sshutil import list_ssh_hosts, parse_ssh_target
from dual_tmux.oc import as_bind, empty_side, is_dst, parse_model, resume_cmd, start_cmd, OcSession
from dual_tmux.store import default_names, normalize_dt
from dual_tmux.log import emit, read_events
from dual_tmux.workpoint import empty_point, empty_times


def test_names():
    assert default_names("cp-gateway") == ("dt-cp-gateway", "op_cp_gateway", "run_cp_gateway")
    assert normalize_dt("dt-x") == "dt-x"
    assert normalize_dt("x") == "dt-x"


def test_source():
    assert legal_source("tm_client")
    assert legal_source("tm_laptop")
    assert not legal_source("laptop")
    assert not legal_source("tm_")
    assert not legal_source("m7")
    assert not legal_source("hostname")


def test_cmd():
    cmd = build_cmd("myserver", "box", "/workspace/app")
    assert "ssh -t myserver" in cmd
    assert "docker exec -it box" in cmd
    assert "/workspace/app" in cmd
    assert build_cmd("myserver", "", "/workspace") == "ssh -t myserver"


def test_parse_ssh_target():
    assert parse_ssh_target("tom7r").dest == "tom7r"
    assert parse_ssh_target("ssh tom7r").dest == "tom7r"
    assert parse_ssh_target("ssh -t tom7r").dest == "tom7r"
    assert parse_ssh_target("ssh -p 22 root@1.2.3.4").dest == "root@1.2.3.4"
    assert parse_ssh_target("ssh -p 22 root@1.2.3.4").port == 22
    t = parse_ssh_target("ssh -p 10700 root@1.2.3.4")
    assert t.dest == "root@1.2.3.4" and t.port == 10700 and t.extra_args == ["-p", "10700"]
    assert parse_ssh_target("root@1.2.3.4").dest == "root@1.2.3.4"


def test_cmd_with_port():
    assert "-p 10700" in build_cmd("root@1.2.3.4", "", "/workspace", 10700)
    assert "-p " not in build_cmd("myserver", "", "/workspace", 22)


def test_list_ssh_hosts(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(
        "Host tom7r\n  HostName 1.2.3.4\n  User root\n  Port 10700\n"
        "Host github.com\n  HostName github.com\nHost *\n  IdentitiesOnly yes\nHost tm_skip?\n"
    )
    assert list_ssh_hosts(cfg) == ["tom7r", "github.com"]
    t = parse_ssh_target("ssh -p 10700 root@1.2.3.4", cfg)
    assert t.stored == "tom7r"
    t2 = parse_ssh_target("ssh -p 22 root@9.9.9.9", cfg)
    assert t2.stored == "root@9.9.9.9"


def test_dst_bind():
    assert parse_model('{"id":"glm-5.1","providerID":"opencode-go"}') == "opencode-go/glm-5.1"
    session = OcSession("ses_1", "brave-knight", model="opencode-go/glm-5.1", agent="build")
    bind = as_bind(session)
    assert bind["tool"] == "opencode"
    assert bind["model"] == "opencode-go/glm-5.1"
    assert bind["session_id"] == "ses_1"
    assert resume_cmd(bind) == "opencode --auto -s ses_1"
    assert start_cmd({"tool": "opencode", "model": "glm-5.1"}) == "opencode --model glm-5.1"
    assert empty_side()["tool"] == "opencode"
    assert is_dst({"trigger": bind, "bullet": bind})
    assert not is_dst({"trigger": bind, "bullet": empty_side()})


def test_event_log(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    emit("freeze.side.fail", name="dt-msg", side="bullet", error="no oc")
    emit("freeze.ok", name="dt-msg", is_dst=False)
    emit("freeze.side.ok", kind="local", point_kind="local", name="dt-msg")
    rows = read_events(kind="freeze")
    assert len(rows) == 3
    assert rows[0]["kind"] == "freeze.side.fail"
    assert rows[2]["kind"] == "freeze.side.ok"
    assert rows[2]["point_kind"] == "local"
    assert "kind" in rows[2] and rows[2]["kind"] == "freeze.side.ok"


def test_workpoint_empty():
    point = empty_point()
    assert point["kind"] == "local"
    assert point["cwd"] == ""
    times = empty_times()
    assert "freeze_at" in times


def test_user():
    assert legal_user("ouc")
    assert legal_user("andy")
    assert not legal_user("tm_laptop")
    assert not legal_user("1ouc")
    assert not legal_user("")
    assert remote_sessions_root("ouc") == "~/ouc/sessions"


def test_config_parse():
    cfg = _parse_toml('client = "tm_laptop"\nserver = "prod"\nuser = "ouc"\nworkspace = "/opt/app"\n')
    assert cfg == AppConfig(client="tm_laptop", server="prod", user="ouc", workspace="/opt/app")


def test_init_rejects_hostname(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    with pytest.raises(SystemExit):
        init_config("laptop", "myserver", "ouc")
    with pytest.raises(SystemExit):
        init_config("tm_laptop", "myserver", "tm_ouc")
    path = init_config("tm_laptop", "myserver", "ouc")
    assert path.is_file()
