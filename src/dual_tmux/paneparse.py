from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

Parser = Callable[[str], "ParsedTurn"]

DEFAULT_PARSER = "opencode@1.18"

BUILD_RE = re.compile(
    r"Build\s*[·•]\s*(.+?)\s*[·•]\s*((?:\d+m\s*)?\d+(?:\.\d+)?s)",
    re.IGNORECASE,
)
RUNNING_RE = re.compile(r"esc\s+interrupt", re.IGNORECASE)
STATUS_RE = re.compile(r"Build(?P<auto>\s+auto)?\s*[·•][^\n]*", re.IGNORECASE)
THOUGHT_RE = re.compile(r"^\s*Thought:\s*", re.IGNORECASE)
REASON_RE = re.compile(r"^\s*The user\b", re.IGNORECASE)
FOOTER_RE = re.compile(r"ctrl\+p commands|OpenCode \d|tokens\b|\$[\d.]+ spent", re.IGNORECASE)
PROMPT_RE = re.compile(
    r"Permission required|Allow once|Allow always|ctrl\+f fullscreen|Ask anything|⇆ select|enter confirm",
    re.IGNORECASE,
)
HOSTKEY_RE = re.compile(
    r"Are you sure you want to continue connecting|"
    r"can't be established|"
    r"Please type 'yes', 'no' or the fingerprint|"
    r"Host key verification failed",
    re.IGNORECASE,
)
CHROME_RE = re.compile(
    r"^(ok |skip |err |· |% |░|▒|▓|┌|└|│|▀|━|╹|OpenCode |Context$|MCP$|LSP$|"
    r"Build auto|Connected$|LSPs are|问候$|▼ MCP)",
)

@dataclass
class ParsedTurn:
    tool: str
    parser: str = ""
    body: str = ""
    model: str = ""
    elapsed: str = ""
    phase: str = "unknown"
    completion_id: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _plain_tail(text: str, n: int = 24) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    keep = [ln for ln in lines if ln.strip()]
    return "\n".join(keep[-n:]).strip()


def _left_col(line: str) -> str:
    line = line.replace("\xa0", " ").rstrip()
    parts = re.split(r" {6,}", line, maxsplit=1)
    return parts[0].rstrip()


def _is_chrome(s: str) -> bool:
    t = s.strip()
    if not t:
        return True
    if set(t) <= set("▀━╹─│┌┐└┘┃▣ "):
        return True
    if t.startswith("┃"):
        return True
    if CHROME_RE.match(t) or FOOTER_RE.search(t):
        return True
    if t.startswith("/") and "opencode" in t.lower():
        return True
    return t.startswith(("~/", "/Users/", "/root/")) and (
        "ctrl+p" in t.lower() or "OpenCode" in t
    )


def parse_plain(text: str, tool: str = "plain") -> ParsedTurn:
    return ParsedTurn(tool=tool, parser="plain", body=_plain_tail(text or ""))


def parse_opencode_1_18(text: str) -> ParsedTurn:
    """OpenCode TUI 1.18: assistant text sits above `▣ Build · Model · elapsed`."""
    text = text or ""
    matches = list(BUILD_RE.finditer(text))
    model, elapsed = "", ""
    if matches:
        last = matches[-1]
        model = last.group(1).strip()
        elapsed = last.group(2).strip()
        start = matches[-2].end() if len(matches) > 1 else 0
        chunk = text[start:last.start()]
    else:
        chunk = text
    body_lines: list[str] = []
    for ln in chunk.splitlines():
        s = _left_col(ln)
        if _is_chrome(s) or THOUGHT_RE.match(s) or REASON_RE.match(s):
            continue
        if s.strip():
            body_lines.append(s.strip())
    body = "\n".join(body_lines).strip()
    running_at = max((match.start() for match in RUNNING_RE.finditer(text)), default=-1)
    status_at = -1
    for match in STATUS_RE.finditer(text):
        if not BUILD_RE.search(match.group(0)):
            status_at = match.start()
    if running_at > status_at:
        phase = "running"
    elif (status_at >= 0 and status_at > running_at) or matches:
        phase = "idle"
    else:
        phase = "unknown"
    completion_id = ""
    if matches:
        stable = f"{model}\0{elapsed}\0{body}"
        completion_id = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]
    return ParsedTurn(
        tool="opencode",
        parser="opencode@1.18",
        body=body,
        model=model,
        elapsed=elapsed,
        phase=phase,
        completion_id=completion_id,
    )


ABC_SPINNER_RE = re.compile(r"^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]|思考中|生成中", re.IGNORECASE)
ABC_FOOTER_RE = re.compile(
    r"session \d{8}-\d{6}|tok/s|^abc[·•]|/model /effort", re.IGNORECASE
)
ABC_STATE_RE = re.compile(
    r"^(cancelled|Agent error|incomplete|回合耗时)\b", re.IGNORECASE
)


def parse_abc_1(text: str) -> ParsedTurn:
    """abc REPL (andybot_core): streaming markdown over a bordered input box.

    Chrome per abc's own presentation discipline (正文 stdout、装饰 stderr):
    box borders, the `│ ` input prompt, the footer status line (model ·
    session id · slash hints), telemetry rows and the thinking spinner.
    """
    text = text or ""
    body_lines: list[str] = []
    phase = "unknown"
    for ln in text.splitlines():
        s = ln.rstrip()
        if not s.strip() or _is_chrome(s):
            continue
        if ABC_FOOTER_RE.search(s):
            phase = "idle" if phase == "unknown" else phase
            continue
        if ABC_SPINNER_RE.search(s):
            phase = "running"
            continue
        if ABC_STATE_RE.match(s.strip()):
            phase = "idle"
            continue
        if s.strip() in {"│", "┃"} or set(s.strip()) <= set("│┃┌┐└┘─━"):
            phase = "idle" if phase == "unknown" else phase
            continue
        body_lines.append(s.strip())
    body = "\n".join(body_lines).strip()
    tail = "\n".join(text.splitlines()[-3:])
    if ABC_SPINNER_RE.search(tail):
        phase = "running"
    completion_id = ""
    if phase == "idle" and body:
        completion_id = hashlib.sha256(f"abc\0{body}".encode()).hexdigest()[:20]
    return ParsedTurn(
        tool="abc",
        parser="abc@1",
        body=body,
        model="",
        elapsed="",
        phase=phase,
        completion_id=completion_id,
    )


PARSERS: dict[str, Parser] = {
    "plain": lambda text: parse_plain(text, "plain"),
    "opencode@1.18": parse_opencode_1_18,
    "abc@1": parse_abc_1,
}

ALIASES: dict[str, str] = {
    "opencode": "opencode@1.18",
    "opencode@1": "opencode@1.18",
    "opencode@1.18.18": "opencode@1.18",
    "abc": "abc@1",
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
