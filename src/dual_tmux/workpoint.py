from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone

from . import tmux as tmux_ops

SSH_RE = re.compile(r"\bssh\b(?:\s+-[^\s]+)*\s+(\S+)")
DOCKER_RE = re.compile(r"docker\s+exec\s+(?:-[^\s]+\s+)*(\S+)")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def empty_point() -> dict:
    return {
        "kind": "local",
        "cwd": "",
        "cmd": "",
        "ssh": "",
        "container": "",
        "directory": "",
        "resume_cmd": "",
        "seen_at": "",
    }


def empty_times() -> dict:
    return {
        "created_at": "",
        "enter_at": "",
        "work_at": "",
        "trigger_oc_at": "",
        "bullet_oc_at": "",
        "freeze_at": "",
        "resume_at": "",
    }


def _ps_command(pid: str) -> str:
    if not pid:
        return ""
    r = subprocess.run(["ps", "-p", pid, "-o", "command="], capture_output=True, text=True)
    return (r.stdout or "").strip()


def _ps_ppid(pid: str) -> str:
    if not pid:
        return ""
    r = subprocess.run(["ps", "-p", pid, "-o", "ppid="], capture_output=True, text=True)
    return (r.stdout or "").strip()


def walk_commands(pid: str, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    current = pid
    while current and current not in seen and len(out) < limit:
        seen.add(current)
        cmd = _ps_command(current)
        if cmd:
            out.append(cmd)
        current = _ps_ppid(current)
    return out


def discover(tmux_name: str) -> dict:
    point = empty_point()
    info = tmux_ops.pane_info(tmux_name)
    point["cwd"] = info.get("cwd") or ""
    point["cmd"] = info.get("cmd") or ""
    point["directory"] = point["cwd"]
    point["kind"] = "local"
    point["seen_at"] = now_iso()
    for cmd in walk_commands(info.get("pid") or ""):
        docker = DOCKER_RE.search(cmd)
        if docker and not point["container"]:
            point["container"] = docker.group(1)
            point["kind"] = "docker"
        ssh = SSH_RE.search(cmd)
        if ssh and not point["ssh"] and ssh.group(1) not in {"-t", "-p", "-o"}:
            dest = ssh.group(1)
            if dest.startswith("-"):
                continue
            point["ssh"] = dest
            if point["kind"] == "local":
                point["kind"] = "ssh"
        if "docker exec" in cmd and not point["resume_cmd"]:
            point["resume_cmd"] = cmd
        elif cmd.startswith("ssh ") and not point["resume_cmd"]:
            point["resume_cmd"] = cmd
    return point


def stamp(data: dict, key: str) -> None:
    times = data.setdefault("times", empty_times())
    times[key] = now_iso()
    data["updated_at"] = times[key]
