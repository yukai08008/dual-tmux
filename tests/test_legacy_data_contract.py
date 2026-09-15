from __future__ import annotations

import shutil
from pathlib import Path

from dual_tmux import memory
from dual_tmux.config import load_config
from dual_tmux.control import ControlService
from dual_tmux.paths import entries_dir
from dual_tmux.recovery import read_state
from dual_tmux.web import _load_web_state

FIXTURE = Path(__file__).parent / "fixtures" / "legacy-v0.4.39"


def _install_fixture(monkeypatch, tmp_path: Path) -> Path:
    target = tmp_path / "dt-home"
    shutil.copytree(FIXTURE, target)
    monkeypatch.setenv("DUAL_TMUX_HOME", str(target))
    return target


def test_legacy_config_and_tunnel_remain_readable(monkeypatch, tmp_path):
    _install_fixture(monkeypatch, tmp_path)

    config = load_config()
    assert config.mode == "hub"
    assert config.client == "tm_legacy"
    assert config.server == "tom7r"

    tunnel = ControlService().get_tunnel("legacy").data
    assert tunnel["name"] == "dt-legacy"
    assert tunnel["runtime"]["container"] == "legacy-box"
    assert tunnel["trigger"]["session_id"] == "ses_trigger"
    assert tunnel["bullet"]["session_id"] == "ses_bullet"


def test_legacy_entry_health_and_memory_remain_readable(monkeypatch, tmp_path):
    _install_fixture(monkeypatch, tmp_path)

    assert (entries_dir() / "run_legacy.cmd").read_text().strip().startswith("ssh tom7r")
    health = read_state("dt-legacy")
    assert health["status"] == "degraded"
    assert health["consecutive_failures"] == 2
    assert health["recovery_attempts"] == 0
    assert health["last_error"] == "legacy transport timeout"
    assert memory.peek_memory()["facts"] == {
        "owner": "legacy-user",
        "policy": "keep-cli",
    }


def test_legacy_web_state_is_normalized_without_losing_history(monkeypatch, tmp_path):
    home = _install_fixture(monkeypatch, tmp_path)
    before = (home / "web-state.json").read_bytes()

    state = _load_web_state()

    assert state["version"] == 1
    assert state["open_tabs"] == ["dt-legacy"]
    assert state["active"] == "dt-legacy"
    assert state["history"]["dt-legacy"]["thread"][0]["text"] == "继续旧任务"
    assert state["history"]["dt-legacy"]["log"][0]["text"] == "旧任务完成"
    assert (home / "web-state.json").read_bytes() == before
