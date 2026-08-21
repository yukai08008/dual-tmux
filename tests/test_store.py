import pytest

from dual_tmux.config import AppConfig, _parse_toml, init_config
from dual_tmux.identity import legal_source, legal_user, remote_sessions_root
from dual_tmux.runtime import build_cmd
from dual_tmux.store import default_names, normalize_dt


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
