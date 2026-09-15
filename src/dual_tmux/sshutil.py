from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_VALUE_FLAGS = {
    "-p",
    "-P",
    "-o",
    "-l",
    "-i",
    "-F",
    "-J",
    "-c",
    "-L",
    "-R",
    "-D",
    "-E",
    "-S",
    "-W",
    "-b",
    "-B",
    "-e",
    "-I",
    "-m",
    "-O",
    "-Q",
    "-w",
}


def ssh_config_path() -> Path:
    return Path.home() / ".ssh" / "config"


def list_ssh_hosts(path: Path | None = None) -> list[str]:
    return [block.alias for block in parse_ssh_config(path) if block.alias]


@dataclass
class HostBlock:
    alias: str
    hostname: str = ""
    user: str = ""
    port: int = 22


def parse_ssh_config(path: Path | None = None) -> list[HostBlock]:
    cfg = path or ssh_config_path()
    if not cfg.is_file():
        return []
    blocks: list[HostBlock] = []
    current: list[str] = []
    fields: dict[str, str] = {}

    def flush() -> None:
        nonlocal current, fields
        hostname = fields.get("hostname", "")
        user = fields.get("user", "")
        port_s = fields.get("port", "22")
        try:
            port = int(port_s)
        except ValueError:
            port = 22
        for alias in current:
            if "*" in alias or "?" in alias:
                continue
            blocks.append(HostBlock(alias=alias, hostname=hostname, user=user, port=port or 22))
        current = []
        fields = {}

    for raw in cfg.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        key_l = key.lower()
        value = rest.strip()
        if key_l == "host":
            flush()
            current = value.split()
            continue
        if key_l in {"hostname", "user", "port"} and value:
            fields[key_l] = value
    flush()
    return blocks


ALIAS_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_ALIAS_OUT_RE = re.compile(r"(?:=\s*|aliased to\s+)'?(.*?)'?\s*$")

_alias_cache: dict[str, str] = {}


def resolve_shell_alias(token: str, *, runner=subprocess.run) -> str:
    """Expand a shell alias like `tom1r` to its ssh command line, or ''.

    Users hop with shell aliases (`alias tom1r="ssh -oPort=24500 root@ip"`);
    ssh config alone cannot tell us the real target when the alias shadows or
    bypasses it. Cached per process; only ssh-looking expansions are used.
    """
    token = (token or "").strip()
    if not ALIAS_NAME_RE.fullmatch(token):
        return ""
    if token in _alias_cache:
        return _alias_cache[token]
    shells = []
    for shell in (os.environ.get("SHELL") or "", "/bin/zsh", "/bin/bash"):
        if shell and shell not in shells:
            shells.append(shell)
    expanded = ""
    for shell in shells:
        try:
            result = runner(
                [shell, "-ic", f"alias {token}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        match = _ALIAS_OUT_RE.search((result.stdout or "").strip())
        candidate = match.group(1).strip() if match else ""
        if candidate.startswith("ssh ") or candidate == "ssh":
            expanded = candidate
            break
    _alias_cache[token] = expanded
    return expanded


@dataclass(frozen=True)
class SshTarget:
    dest: str
    port: int = 22
    matched_alias: str = ""

    @property
    def extra_args(self) -> list[str]:
        if self.port and self.port != 22:
            return ["-p", str(self.port)]
        return []

    @property
    def stored(self) -> str:
        return self.matched_alias or self.dest


def parse_ssh_target(raw: str, config_path: Path | None = None) -> SshTarget:
    parts = raw.strip().split()
    if not parts:
        return SshTarget("")
    if parts[0].lower() in {"ssh", "ssh.exe"}:
        parts = parts[1:]
    port = 22
    dest = ""
    user_flag = ""
    i = 0
    while i < len(parts):
        part = parts[i]
        option_l = part.lower()
        if option_l.startswith("-oport=") and part.split("=", 1)[1].isdigit():
            port = int(part.split("=", 1)[1])
            i += 1
            continue
        if part.startswith("-p") and part != "-p" and part[2:].isdigit():
            port = int(part[2:])
            i += 1
            continue
        if part in _VALUE_FLAGS:
            if part in {"-p", "-P"} and i + 1 < len(parts) and parts[i + 1].isdigit():
                port = int(parts[i + 1])
            elif part == "-l" and i + 1 < len(parts):
                user_flag = parts[i + 1]
            elif (
                part == "-o"
                and i + 1 < len(parts)
                and parts[i + 1].lower().startswith("port=")
                and parts[i + 1].split("=", 1)[1].isdigit()
            ):
                port = int(parts[i + 1].split("=", 1)[1])
            i += 2
            continue
        if part.startswith("-"):
            i += 1
            continue
        if not dest:
            # The first positional token is the SSH destination. Everything
            # after it is the remote command and must not overwrite the host.
            dest = part
        i += 1
    user, host = _split_user_host(dest)
    if user_flag and not user:
        user = user_flag
        dest = f"{user}@{host}" if host else dest
    alias = match_ssh_alias(host=host or dest, user=user, port=port, path=config_path)
    return SshTarget(dest=dest, port=port or 22, matched_alias=alias)


def _split_user_host(dest: str) -> tuple[str, str]:
    if dest.startswith("[") and "]:" in dest:
        dest = dest[1:].split("]:", 1)[0]
    if "@" in dest:
        user, _, host = dest.partition("@")
        return user, host
    return "", dest


def match_ssh_alias(host: str, user: str = "", port: int = 22, path: Path | None = None) -> str:
    if not host:
        return ""
    host_l = host.lower()
    for block in parse_ssh_config(path):
        names = {block.alias.lower()}
        if block.hostname:
            names.add(block.hostname.lower())
        if host_l not in names:
            continue
        if block.port and port not in (22, block.port) and block.port != port:
            continue
        if user and block.user and user != block.user:
            continue
        return block.alias
    return ""


def normalize_server(raw: str, config_path: Path | None = None) -> str:
    target = parse_ssh_target(raw, config_path)
    return target.stored
