from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone

from . import tmux as tmux_ops
from .sshutil import list_ssh_hosts, parse_ssh_target

DOCKER_RE = re.compile(r"docker\s+exec\s+(?:-[^\s]+\s+)*(\S+)")
STARSHIP_SEP = re.compile(r"\s*[❯]\s*")
PROMPT_STATUS = re.compile(r"^[✘✗✓✔!×\s]+")
BOX_HEAD = re.compile(r"┌─(?:\([^)]+\)\s*)?(.+)$")
BOX_TAIL = re.compile(r"└─\s*[#$]\s*(.*)$")
CLASSIC = re.compile(r"^(?:\([^)]+\)\s*)?(\S+@\S+):(.+?)[#$]\s*(.*)$")


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
        "hops": [],
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


def _children(pid: str) -> list[str]:
    if not pid:
        return []
    r = subprocess.run(["pgrep", "-P", pid], capture_output=True, text=True)
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def walk_commands(pid: str, limit: int = 16) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    queue = [pid]
    while queue and len(out) < limit:
        current = queue.pop(0)
        if not current or current in seen:
            continue
        seen.add(current)
        cmd = _ps_command(current)
        if cmd:
            out.append(cmd)
        queue.extend(_children(current))
    return out


def _parse_prompts(text: str) -> list[dict]:
    rows: list[dict] = []
    pending: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        box = BOX_HEAD.search(line)
        if box and "└" not in line:
            rest = box.group(1).strip()
            if ":" in rest:
                left, path = rest.rsplit(":", 1)
                pending = {"host": left, "path": path, "command": ""}
            continue
        if pending is not None:
            tail = BOX_TAIL.search(line)
            if tail:
                pending["command"] = tail.group(1).strip()
                rows.append(pending)
                pending = None
                continue
        if "" in line or "❯" in line:
            parts = [p for p in STARSHIP_SEP.split(line) if p is not None]
            parts = [p.strip() for p in parts]
            if len(parts) >= 2:
                host = PROMPT_STATUS.sub("", parts[0]).strip()
                rows.append(
                    {
                        "host": host,
                        "path": parts[1],
                        "command": " ".join(parts[2:]).strip(),
                    }
                )
                continue
        classic = CLASSIC.match(line)
        if classic:
            rows.append(
                {
                    "host": classic.group(1),
                    "path": classic.group(2).rstrip(),
                    "command": classic.group(3).strip(),
                }
            )
    if pending is not None:
        rows.append(pending)
    return rows


def _compact(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        if (
            out
            and out[-1]["host"] == row["host"]
            and out[-1]["path"] == row["path"]
            and not out[-1]["command"]
        ):
            out[-1]["command"] = row["command"]
            continue
        out.append(dict(row))
    return out


def parse_hops(text: str) -> list[dict]:
    stops = _compact(_parse_prompts(text))
    hops: list[dict] = []
    for i, stop in enumerate(stops[:-1]):
        nxt = stops[i + 1]
        if not stop.get("command"):
            continue
        if (stop["host"], stop["path"]) == (nxt["host"], nxt["path"]):
            continue
        hops.append(
            {
                "from_host": stop["host"],
                "from_path": stop["path"],
                "command": stop["command"],
                "to_host": nxt["host"],
                "to_path": nxt["path"],
            }
        )
    return hops


def _from_hops(hops: list[dict]) -> dict:
    point = empty_point()
    aliases = set(list_ssh_hosts())
    for hop in hops:
        cmd = hop.get("command") or ""
        docker = DOCKER_RE.search(cmd)
        if docker:
            point["container"] = docker.group(1)
            point["kind"] = "docker"
        token = cmd.split()[0] if cmd else ""
        if token in aliases or cmd.startswith("ssh ") or token == "ssh":
            target = parse_ssh_target(cmd if cmd.startswith("ssh") else token)
            point["ssh"] = target.stored or token
            if point["kind"] == "local":
                point["kind"] = "ssh"
        if hop.get("to_host") and hop.get("from_host") and hop["to_host"] != hop["from_host"]:
            if point["kind"] == "local":
                point["kind"] = "ssh"
            if not point["ssh"]:
                point["ssh"] = token
    if hops:
        last = hops[-1]
        point["cwd"] = last.get("to_path") or ""
        point["directory"] = point["cwd"]
        point["hops"] = hops
        point["resume_cmd"] = " && ".join(h["command"] for h in hops if h.get("command"))
    return point


def _from_processes(pid: str, point: dict) -> None:
    for cmd in walk_commands(pid):
        if cmd.startswith("ssh ") or " ssh " in f" {cmd}":
            target = parse_ssh_target(cmd)
            if not point["ssh"]:
                point["ssh"] = target.stored or target.dest
            if point["kind"] == "local":
                point["kind"] = "ssh"
            if not point["resume_cmd"]:
                point["resume_cmd"] = cmd
        docker = DOCKER_RE.search(cmd)
        if docker:
            if not point["container"]:
                point["container"] = docker.group(1)
            point["kind"] = "docker"
            if "docker exec" in cmd and "docker exec" not in (point.get("resume_cmd") or ""):
                point["resume_cmd"] = ((point.get("resume_cmd") or "") + " && " + cmd).strip(" &")


def discover(tmux_name: str) -> dict:
    info = tmux_ops.pane_info(tmux_name)
    process_commands = [info.get("cmd") or "", *walk_commands(info.get("pid") or "")]
    from .agentclient import detect_name

    if detect_name(process_commands):
        point = empty_point()
        point["cmd"] = info.get("cmd") or ""
        point["cwd"] = info.get("cwd") or ""
        point["directory"] = point["cwd"]
        point["seen_at"] = now_iso()
        return point
    hops = parse_hops(tmux_ops.capture_pane(tmux_name))
    point = _from_hops(hops)
    point["cmd"] = info.get("cmd") or ""
    point["seen_at"] = now_iso()
    if not point["cwd"]:
        point["cwd"] = info.get("cwd") or ""
        point["directory"] = point["cwd"]
    _from_processes(info.get("pid") or "", point)
    return point


def apply_runtime(data: dict, point: dict) -> None:
    runtime = data.setdefault("runtime", {})
    if point.get("ssh"):
        target = parse_ssh_target(point.get("resume_cmd") or point["ssh"])
        runtime["server"] = target.stored or point["ssh"]
        runtime["ssh_port"] = target.port or 22
    if point.get("container"):
        runtime["container"] = point["container"]
    # tmux reports the local shell cwd while a direct SSH command is running.
    # Only a parsed remote prompt/hop proves the remote directory.
    if (
        point.get("directory")
        and point["kind"] in {"ssh", "docker"}
        and point.get("hops")
    ):
        runtime["directory"] = point["directory"]
    if point.get("container") or (point.get("ssh") and runtime.get("server")):
        from .runtime import build_cmd

        port = int(runtime.get("ssh_port") or 22)
        if point.get("resume_cmd") and not point.get("container") and not point.get("hops"):
            runtime["cmd"] = point["resume_cmd"]
        else:
            runtime["cmd"] = build_cmd(
                runtime.get("server") or point.get("ssh") or "",
                runtime.get("container") or "",
                runtime.get("directory") or "/workspace",
                port,
            )


def capture_runtime(data: dict, point: dict) -> None:
    """Make runtime describe the bullet's observed work point, including local drift."""
    if (point.get("kind") or "local") != "local":
        apply_runtime(data, point)
        return
    runtime = data.setdefault("runtime", {})
    runtime.update(
        server="",
        container="",
        directory=point.get("directory") or point.get("cwd") or "",
        cmd="",
    )


def canonical_runtime_point(data: dict, point: dict) -> dict:
    """Represent a live remote pane using its persisted runtime endpoint."""
    out = dict(point)
    if out.get("kind") not in {"ssh", "docker"}:
        return out
    runtime = data.get("runtime") or {}
    out["ssh"] = runtime.get("server") or out.get("ssh") or ""
    out["container"] = runtime.get("container") or out.get("container") or ""
    out["directory"] = runtime.get("directory") or out.get("directory") or ""
    out["cwd"] = out["directory"]
    out["resume_cmd"] = runtime.get("cmd") or out.get("resume_cmd") or ""
    out["kind"] = "docker" if out["container"] else "ssh"
    return out


def stamp(data: dict, key: str) -> None:
    times = data.setdefault("times", empty_times())
    times[key] = now_iso()
    data["updated_at"] = times[key]
