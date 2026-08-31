import json

import pytest

from dual_tmux.agents import (
    capability_matrix,
    get_adapter,
    list_adapters,
    require_adapter,
)


def test_registry_resolves_three_clients_and_aliases():
    assert [item.name for item in list_adapters()] == ["opencode", "codex", "claude"]
    assert get_adapter("codex-cli").name == "codex"
    assert get_adapter("claude-code").name == "claude"
    assert get_adapter("bash") is None
    with pytest.raises(ValueError, match="unsupported agent"):
        require_adapter("bash")


def test_capabilities_are_truthful_about_session_lifecycle():
    opencode = require_adapter("opencode")
    assert opencode.supports("start")
    assert opencode.supports("session_freeze")
    assert opencode.supports("resume")
    assert opencode.supports("model")

    for name in ("codex", "claude"):
        adapter = require_adapter(name)
        assert adapter.supports("detect")
        assert adapter.supports("version")
        assert adapter.supports("send")
        assert adapter.supports("metadata_freeze")
        assert not adapter.supports("session_freeze")
        assert not adapter.supports("resume")
        assert not adapter.supports("model")


def test_capability_matrix_is_json_safe():
    encoded = json.dumps(capability_matrix())
    assert '"name": "opencode"' in encoded
    assert '"name": "codex"' in encoded
    assert '"name": "claude"' in encoded
