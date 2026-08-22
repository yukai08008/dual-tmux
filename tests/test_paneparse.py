from dual_tmux.paneparse import (
    list_parsers,
    parse_opencode,
    parse_pane,
    parser_id_for_side,
    resolve_parser_id,
)


SAMPLE = """
░▒▓ ~/.du/o/op_msg2  opencode --model xs-grok/grok-4.6
     OpenCode 有全局配置
  ┃  帮我看下 rabbitmq admin的密码
     Thought: 1.1s
     The user wants to know
     dev 实例 rabbit_mq_dev：
     - 用户：admin
     - 密码：andy@2026
     ▣  Build · Grok 4.6 · 1m 8s
  ┃  Build · Grok 4.6 XS CP Gateway
"""


def test_parse_opencode_extracts_body_model_elapsed():
    got = parse_opencode(SAMPLE)
    assert got.tool == "opencode"
    assert got.parser == "opencode@1.18"
    assert "Grok 4.6" in got.model
    assert "1m 8s" in got.elapsed
    assert "admin" in got.body
    assert "andy@2026" in got.body
    assert "Thought:" not in got.body
    assert "▣" not in got.body


def test_parse_pane_dispatches_tool():
    got = parse_pane("hello\\nworld", "other")
    assert got.parser == "plain"
    assert "hello" in got.body


def test_parser_registry_and_aliases():
    assert "opencode@1.18" in list_parsers()
    assert resolve_parser_id("opencode") == "opencode@1.18"
    assert resolve_parser_id("opencode@1.18.18") == "opencode@1.18"
    assert resolve_parser_id("opencode@9.9") == "opencode@1.18"
    assert parser_id_for_side({"tool": "opencode"}) == "opencode@1.18"
    assert parser_id_for_side({"tool": "opencode", "parser": "plain"}) == "plain"
    trigger = parser_id_for_side({"tool": "opencode", "parser": "opencode@1.18"})
    bullet = parser_id_for_side({"tool": "opencode", "parser": "plain"})
    assert trigger != bullet
