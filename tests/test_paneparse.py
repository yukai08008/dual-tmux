from pathlib import Path

from dual_tmux.paneparse import (
    list_parsers,
    parse_opencode,
    parse_pane,
    parser_id_for_side,
    resolve_parser_id,
)

FIXTURE = Path(__file__).parent / "fixtures" / "opencode_1_18_portal.txt"

RABBIT = """
░▒▓ ~/.du/o/op_msg2  opencode --model xs-grok/grok-4.6
     Thought: 650ms
     The user asked for the RabbitMQ admin password.
     dev 实例 rabbit_mq_dev_24637_24638：
     - 用户：admin
     - 密码：andy@2026
     ▣  Build · Grok 4.6 · 1m 8s
  ┃  Build · Grok 4.6 XS CP Gateway
   /Users/andy/.dual-tmux/ops/op_msg2    235.3K  ctrl+p commands    • OpenCode 1.18.18
"""


def test_portal_fixture_is_reply_not_footer():
    text = FIXTURE.read_text()
    got = parse_opencode(text)
    assert got.parser == "opencode@1.18"
    assert got.model == "Grok 4.6"
    assert got.elapsed == "2.5s"
    assert "你好" in got.body
    assert "有任务直接说" in got.body
    assert "ctrl+p" not in got.body.lower()
    assert "OpenCode 1.18" not in got.body
    assert "/Users/" not in got.body
    assert "34.3K" not in got.body
    assert "Thought:" not in got.body
    assert "The user" not in got.body


def test_rabbitmq_sample_keeps_answer_and_timing():
    got = parse_opencode(RABBIT)
    assert "Grok 4.6" in got.model
    assert "1m 8s" in got.elapsed
    assert "admin" in got.body
    assert "andy@2026" in got.body
    assert "Thought:" not in got.body
    assert "The user asked" not in got.body
    assert "ctrl+p" not in got.body
    assert got.phase == "idle"
    assert got.completion_id


def test_running_opencode_is_not_mistaken_for_a_completed_turn():
    got = parse_opencode(
        "┃ Build auto · Grok 4.6\nThought: 106ms\n▣ Build · grok-4.6\n■■■ esc interrupt"
    )
    assert got.phase == "running"
    assert got.elapsed == ""
    assert got.completion_id == ""


def test_parse_pane_unknown_tool_is_plain():
    got = parse_pane("hello\nworld", "other")
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
