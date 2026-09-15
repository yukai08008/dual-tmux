from __future__ import annotations

import ast
import inspect
import json
import textwrap
from pathlib import Path

from dual_tmux.api_contract import control_envelope_manifest, web_api_manifest
from dual_tmux.control import ControlError, ControlResult, operation_catalog
from dual_tmux.web import Handler

ROOT = Path(__file__).resolve().parents[1]
API_CONTRACT = ROOT / "docs" / "contracts" / "web-api-v1.json"
CONTROL_CONTRACT = ROOT / "docs" / "contracts" / "control-envelope-v1.json"


def _snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _handler_api_paths(method_name: str) -> set[str]:
    source = textwrap.dedent(inspect.getsource(getattr(Handler, method_name)))
    tree = ast.parse(source)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("/api/")
        and not node.value.endswith("/")
    }


def test_web_api_manifest_matches_versioned_contract():
    assert web_api_manifest() == _snapshot(API_CONTRACT)


def test_web_api_contract_covers_live_handler_routes():
    contracted = {
        (row["method"], row["path"])
        for row in web_api_manifest()["endpoints"]
    }
    live = {
        *(('GET', path) for path in _handler_api_paths("do_GET")),
        *(('POST', path) for path in _handler_api_paths("do_POST")),
    }
    assert contracted == live


def test_web_api_contract_records_migration_metadata():
    rows = web_api_manifest()["endpoints"]
    assert len(rows) == 48
    assert len({(row["method"], row["path"]) for row in rows}) == len(rows)
    assert all(
        row["request"]
        and row["response"]
        and row["errors"]
        and row["risk"]
        for row in rows
    )
    assert {row["risk"] for row in rows} <= {
        "read",
        "write",
        "execute",
        "destructive",
        "high-risk",
        "network-read",
        "network-write",
    }


def test_web_api_operations_follow_control_catalog_risk():
    catalog = {row["name"]: row for row in operation_catalog()}
    meta_operations = {"agent.capabilities", "control.operations"}
    for endpoint in web_api_manifest()["endpoints"]:
        operation = endpoint["operation"]
        if not operation or operation in meta_operations:
            continue
        assert operation in catalog
        assert endpoint["risk"] == catalog[operation]["risk"]


def test_control_envelope_matches_contract_and_runtime_shapes():
    contract = control_envelope_manifest()
    assert contract == _snapshot(CONTROL_CONTRACT)

    success = ControlResult("test.operation", {"value": 1}, "test.audit").as_dict()
    assert list(success) == contract["success"]["required"]
    assert success["ok"] is True

    error = ControlError("test_error", "failed", status=409, detail={"id": 1})
    payload = error.as_dict()
    assert list(payload) == contract["error"]["required"]
    assert list(payload["error"]) == contract["error"]["error_required"]
    assert payload["ok"] is False
    assert error.status == 409
