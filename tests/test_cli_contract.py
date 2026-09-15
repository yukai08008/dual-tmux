from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from dual_tmux.cli import build_parser
from dual_tmux.cli_contract import cli_manifest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "contracts" / "cli-v1.json"


def _snapshot() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_cli_parser_matches_versioned_contract():
    """Any public syntax change must be reviewed as an explicit contract edit."""
    assert cli_manifest(build_parser()) == _snapshot()


def test_cli_contract_covers_all_current_command_families():
    manifest = _snapshot()
    assert manifest["schema_version"] == 1
    assert manifest["program"] == "dt"
    assert set(manifest["commands"]) == {
        "bind",
        "branch",
        "capture",
        "config",
        "cron",
        "daemon",
        "doctor",
        "drop",
        "enter",
        "feishu",
        "freeze",
        "health",
        "hotfix",
        "inspect",
        "log",
        "ls",
        "make",
        "mem",
        "model",
        "new",
        "note",
        "notes",
        "ownership",
        "park",
        "pull",
        "push",
        "re",
        "recover",
        "resume",
        "rm",
        "send",
        "show",
        "skill",
        "tick",
        "upgrade",
        "web",
        "work",
    }
    assert set(manifest["commands"]["skill"]["commands"]) == {
        "disable",
        "enable",
        "import",
        "log",
        "ls",
        "teach",
        "used",
    }
    assert set(manifest["commands"]["feishu"]["commands"]) == {
        "dispatch",
        "pair",
        "poll",
        "status",
        "sync",
        "unbind",
    }


def test_cli_contract_records_flags_defaults_and_choices():
    commands = _snapshot()["commands"]
    new_args = {item["dest"]: item for item in commands["new"]["arguments"]}
    assert new_args["local"]["flags"] == ["--local"]
    assert new_args["local"]["default"] is False
    assert new_args["container"]["default"] == ""

    freeze_args = {
        item["dest"]: item for item in commands["freeze"]["arguments"]
    }
    assert freeze_args["tool"]["choices"] == [
        "auto",
        "opencode",
        "codex",
        "claude",
    ]
    assert freeze_args["tool"]["default"] == "auto"

    web_args = {item["dest"]: item for item in commands["web"]["arguments"]}
    assert web_args["port"]["type"] == "int"
    assert web_args["port"]["default"] == 8787


def test_non_web_cli_import_does_not_load_web_module():
    script = (
        "import sys; import dual_tmux.cli; "
        "assert 'dual_tmux.web' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
