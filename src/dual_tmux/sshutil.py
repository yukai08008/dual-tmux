from __future__ import annotations

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
    cfg = path or ssh_config_path()
    if not cfg.is_file():
        return []
    hosts: list[str] = []
    for raw in cfg.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        if key.lower() != "host":
            continue
        for token in rest.split():
            if "*" in token or "?" in token:
                continue
            if token not in hosts:
                hosts.append(token)
    return hosts


@dataclass(frozen=True)
class SshTarget:
    dest: str
    port: int = 22

    @property
    def extra_args(self) -> list[str]:
        if self.port and self.port != 22:
            return ["-p", str(self.port)]
        return []


def parse_ssh_target(raw: str) -> SshTarget:
    parts = raw.strip().split()
    if not parts:
        return SshTarget("")
    if parts[0].lower() in {"ssh", "ssh.exe"}:
        parts = parts[1:]
    port = 22
    dest = ""
    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith("-p") and part != "-p" and part[2:].isdigit():
            port = int(part[2:])
            i += 1
            continue
        if part in _VALUE_FLAGS:
            if part in {"-p", "-P"} and i + 1 < len(parts) and parts[i + 1].isdigit():
                port = int(parts[i + 1])
            i += 2
            continue
        if part.startswith("-"):
            i += 1
            continue
        dest = part
        i += 1
    return SshTarget(dest=dest, port=port or 22)


def normalize_server(raw: str) -> str:
    return parse_ssh_target(raw).dest
