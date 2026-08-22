from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Callable

Parser = Callable[[str], "ParsedTurn"]

DEFAULT_PARSER = "opencode@1.18"


@dataclass
class ParsedTurn:
    tool: str
    parser: str = ""
    body: str = ""
    model: str = ""
    elapsed: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _plain_tail(text: str, n: int = 24) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    keep = [ln for ln in lines if ln.strip()]
    return "\n".join(keep[-n:]).strip()


def _trim(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def parse_plain(text: str, tool: str = "plain") -> ParsedTurn:
    return ParsedTurn(tool=tool, parser="plain", body=_plain_tail(text or ""))


def parse_opencode_1_18(text: str) -> ParsedTurn:
    """OpenCode TUI ~1.18: `Build · Model · 1m 8s`, Thought:, box-drawing chrome."""
    text = text or ""
    build_re = re.compile(
        r"Build\s*[·•]\s*(.+?)\s*[·•]\s*((?:\d+m\s*)?\d+(?:\.\d+)?s)",
        re.IGNORECASE,
    )
    model_only_re = re.compile(
        r"Build\s*[·•]\s*([A-Za-z][A-Za-z0-9 ._+-]{1,40})",
        re.IGNORECASE,
    )
    model_flag_re = re.compile(r"opencode\s+--model\s+(\S+)")
    thought_re = re.compile(r"^\s*Thought:\s*", re.IGNORECASE)
    noise_re = re.compile(
        r"^(ok |skip |err |· |% |░|▒|▓|┌|└|│|▀|━|╹|OpenCode |Context$|MCP$|LSP$|"
        r"Build auto|ctrl\+p|tokens|used$|spent$|Connected$|LSPs are)",
    )
    model, elapsed = "", ""
    for m in build_re.finditer(text):
        model = m.group(1).strip()
        elapsed = (m.group(2) or "").strip()
    if not model:
        only = list(model_only_re.finditer(text))
        if only:
            model = only[-1].group(1).strip()
    if not model:
        flag = model_flag_re.search(text)
        if flag:
            model = flag.group(1)
    lines = text.splitlines()
    chunks: list[list[str]] = [[]]
    for ln in lines:
        s = ln.replace("\xa0", " ").rstrip()
        if "▣" in s and "Build" in s:
            chunks.append([])
            continue
        if thought_re.match(s):
            continue
        if s.strip().startswith("┃"):
            continue
        if noise_re.match(s.lstrip()) or set(s.strip()) <= set("▀━╹─│┌┐└┘ "):
            continue
        if "tokens" in s.lower() and "used" in s.lower():
            continue
        chunks[-1].append(s)
    bodies = ["\n".join(_trim(c)).strip() for c in chunks]
    bodies = [b for b in bodies if len(b) > 8]
    body = bodies[-1] if bodies else ""
    return ParsedTurn(
        tool="opencode",
        parser="opencode@1.18",
        body=body,
        model=model,
        elapsed=elapsed,
    )


PARSERS: dict[str, Parser] = {
    "plain": lambda text: parse_plain(text, "plain"),
    "opencode@1.18": parse_opencode_1_18,
}

ALIASES: dict[str, str] = {
    "opencode": "opencode@1.18",
    "opencode@1": "opencode@1.18",
    "opencode@1.18.18": "opencode@1.18",
}


def list_parsers() -> list[str]:
    return sorted(PARSERS)


def resolve_parser_id(raw: str = "") -> str:
    name = (raw or "").strip() or DEFAULT_PARSER
    name = ALIASES.get(name, name)
    if name in PARSERS:
        return name
    if "@" in name:
        tool, _, _ver = name.partition("@")
        fallback = ALIASES.get(tool, "")
        if fallback in PARSERS:
            return fallback
    return "plain"


def parser_id_for_side(info: dict | None) -> str:
    info = info or {}
    pinned = (info.get("parser") or "").strip()
    if pinned:
        return resolve_parser_id(pinned)
    tool = (info.get("tool") or "opencode").strip() or "opencode"
    return resolve_parser_id(tool)


def parse_pane(text: str, parser_id: str = "") -> ParsedTurn:
    pid = resolve_parser_id(parser_id)
    fn = PARSERS.get(pid) or PARSERS["plain"]
    got = fn(text or "")
    got.parser = pid
    return got


def parse_opencode(text: str) -> ParsedTurn:
    return parse_pane(text, "opencode@1.18")
