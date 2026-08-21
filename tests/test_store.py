from dual_tmux.runtime import build_cmd
from dual_tmux.store import default_names, normalize_dt
from dual_tmux.identity import legal_source


def test_names():
    assert default_names("cp-gateway") == ("dt-cp-gateway", "op_cp_gateway", "run_cp_gateway")
    assert normalize_dt("dt-x") == "dt-x"
    assert normalize_dt("x") == "dt-x"


def test_source():
    assert legal_source("tm_andy_ouc")
    assert legal_source("tm_m7")
    assert not legal_source("m7")
    assert not legal_source("andydeMacBook-Pro")
    assert not legal_source("tmux_general_sessions")


def test_cmd():
    cmd = build_cmd("tom7r", "box", "/workspace/app")
    assert "ssh -t tom7r" in cmd
    assert "docker exec -it box" in cmd
    assert "/workspace/app" in cmd
    assert build_cmd("tom7r", "", "/workspace") == "ssh -t tom7r"
