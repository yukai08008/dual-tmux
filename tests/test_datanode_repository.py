import json
from pathlib import Path

from datanode import (
    AgentRole,
    AgentSessionNode,
    LocalEndpointNode,
    RoleBindingNode,
    TunnelNode,
    TunnelRepository,
)
from dual_tmux.control import ControlService


def _make_node(name: str = "dt-repo-demo") -> TunnelNode:
    return TunnelNode(
        name=name,
        op=f"op_{name.removeprefix('dt-')}",
        run=f"run_{name.removeprefix('dt-')}",
        endpoint=LocalEndpointNode(directory="/test/dir"),
        trigger=RoleBindingNode(
            tunnel_name=name,
            role=AgentRole.TRIGGER,
            session=AgentSessionNode(
                session_id="ses_trig_repo",
                tool="opencode",
                model="test/model",
            ),
        ),
        bullet=RoleBindingNode(
            tunnel_name=name,
            role=AgentRole.BULLET,
            session=AgentSessionNode(
                session_id="ses_bull_repo",
                tool="opencode",
                model="test/model",
            ),
        ),
    )


def test_repository_save_get_and_exists(tmp_path: Path):
    repo = TunnelRepository(root=tmp_path)
    node = _make_node("dt-my-tunnel")

    assert not repo.exists("dt-my-tunnel")
    path = repo.save(node)
    assert path.is_file()
    assert repo.exists("dt-my-tunnel")
    assert repo.exists("my-tunnel")

    loaded = repo.get("dt-my-tunnel")
    assert loaded.name == "dt-my-tunnel"
    assert loaded.is_dst is True
    assert loaded.trigger.session.session_id == "ses_trig_repo"
    assert loaded.bullet.session.session_id == "ses_bull_repo"


def test_repository_list_filters_corrupted_files(tmp_path: Path):
    repo = TunnelRepository(root=tmp_path)
    repo.save(_make_node("dt-one"))
    repo.save(_make_node("dt-two"))

    # Create corrupted file
    (tmp_path / "dt-bad.json").write_text("{invalid json", encoding="utf-8")

    nodes = repo.list()
    names = [n.name for n in nodes]
    assert names == ["dt-one", "dt-two"]


def test_repository_delete(tmp_path: Path):
    repo = TunnelRepository(root=tmp_path)
    node = _make_node("dt-del")
    repo.save(node)
    assert repo.exists("dt-del")

    assert repo.delete("dt-del") is True
    assert not repo.exists("dt-del")
    assert repo.delete("dt-del") is False


def test_repository_preserves_extra_fields_on_save(tmp_path: Path):
    repo = TunnelRepository(root=tmp_path)
    node = _make_node("dt-preserve")
    path = repo.save(node)

    # Add custom extra field to JSON
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["custom_meta"] = {"key": "val"}
    path.write_text(json.dumps(raw), encoding="utf-8")

    # Save modified node through repository (using immutable model_copy)
    updated_session = node.trigger.session.model_copy(update={"model": "new/model"})
    updated_trigger = node.trigger.model_copy(update={"session": updated_session})
    updated_node = node.model_copy(update={"trigger": updated_trigger})
    repo.save(updated_node)

    updated_raw = json.loads(path.read_text(encoding="utf-8"))
    assert updated_raw["trigger"]["model"] == "new/model"
    assert updated_raw["custom_meta"] == {"key": "val"}


def test_control_service_exposes_tunnel_nodes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    repo = TunnelRepository(root=tmp_path / "tunnels")
    repo.save(_make_node("dt-service-demo"))

    service = ControlService(repository=repo)
    nodes = service.list_tunnel_nodes()
    assert len(nodes) == 1
    assert nodes[0].name == "dt-service-demo"

    node = service.get_tunnel_node("dt-service-demo")
    assert node.name == "dt-service-demo"
    assert node.bullet.session.session_id == "ses_bull_repo"


def test_repository_save_raw_and_get_or_none(tmp_path: Path):
    repo = TunnelRepository(root=tmp_path)
    assert repo.get_or_none("dt-nonexistent") is None

    raw_data = {
        "name": "dt-raw-demo",
        "op": "op_raw_demo",
        "run": "run_raw_demo",
        "auto_recover": True,
    }
    node = repo.save_raw(raw_data)
    assert node.name == "dt-raw-demo"
    assert node.auto_recover is True

    loaded = repo.get_or_none("dt-raw-demo")
    assert loaded is not None
    assert loaded.name == "dt-raw-demo"
    assert loaded.auto_recover is True


def test_store_save_validates_tunnel_invariants(tmp_path: Path, monkeypatch):
    import pytest
    from pydantic import ValidationError

    from dual_tmux.store import save

    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    tunnels_dir = tmp_path / "tunnels"
    tunnels_dir.mkdir(parents=True, exist_ok=True)

    # Illegal tunnel: trigger and bullet cannot bind the same session
    bad_data = {
        "name": "dt-bad",
        "op": "op_bad",
        "run": "run_bad",
        "trigger": {"session_id": "ses_conflict"},
        "bullet": {"session_id": "ses_conflict"},
    }
    with pytest.raises(ValueError, match="trigger and bullet cannot bind the same session"):
        save(tunnels_dir / "dt-bad.json", bad_data)

    # Illegal tunnel name pattern
    bad_name_data = {
        "name": "illegal_name_without_dt_prefix",
        "op": "op_illegal",
        "run": "run_illegal",
    }
    with pytest.raises(ValidationError):
        save(tunnels_dir / "dt-illegal.json", bad_name_data)
