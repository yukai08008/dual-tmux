from dual_tmux.config import AppConfig, _parse_toml
from dual_tmux.identity import legal_source
from dual_tmux.runtime import build_cmd
from dual_tmux.store import default_names, normalize_dt


def test_names():
    assert default_names("cp-gateway") == ("dt-cp-gateway", "op_cp_gateway", "run_cp_gateway")
    assert normalize_dt("dt-x") == "dt-x"
    assert normalize_dt("x") == "dt-x"


def test_source():
    assert legal_source("tm_client")
    assert not legal_source("m7")
    assert not legal_source("hostname")


def test_cmd():
    cmd = build_cmd("myserver", "box", "/workspace/app")
    assert "ssh -t myserver" in cmd
    assert "docker exec -it box" in cmd
    assert "/workspace/app" in cmd
    assert build_cmd("myserver", "", "/workspace") == "ssh -t myserver"


def test_config_parse():
    cfg = _parse_toml('client = "laptop"\nserver = "prod"\nworkspace = "/opt/app"\n')
    assert cfg == AppConfig(client="laptop", server="prod", workspace="/opt/app")
