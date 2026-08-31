from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .workpoint import now_iso

SUPPORTED = ("opencode", "codex", "claude")
ALIASES = {
    "opencode": "opencode",
    "codex": "codex",
    "codex-cli": "codex",
    "claude": "claude",
    "claude-code": "claude",
}
VERSION_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?)")
Runner = Callable[..., subprocess.CompletedProcess]


def empty() -> dict[str, str]:
    return {
        "name": "",
        "version": "",
        "version_output": "",
        "executable": "",
        "location": "",
        "host": "",
        "container": "",
        "collected_at": "",
        "error": "",
    }


def normalize_name(raw: str = "") -> str:
    name = Path((raw or "").strip()).name.lower()
    for suffix in (".exe", ".js", ".mjs", ".cjs"):
        name = name.removesuffix(suffix)
    return ALIASES.get(name, "")


def detect_name(commands: list[str]) -> str:
    for command in commands:
        direct = normalize_name(command)
        if direct:
            return direct
        try:
            tokens = shlex.split(command or "")[:4]
        except ValueError:
            tokens = (command or "").split()[:4]
        for token in tokens:
            found = normalize_name(token)
            if found:
                return found
    return ""


def resolve_name(pane_command: str = "", requested: str = "") -> str:
    """Prefer the actual foreground Agent CLI, then the requested tool."""
    return detect_name([pane_command]) or normalize_name(requested)


def parse_version_output(name: str, raw: str) -> tuple[str, str]:
    del name  # Reserved for client-specific parsers when formats diverge.
    lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
    output = lines[0][:240] if lines else ""
    match = VERSION_RE.search(output)
    return (match.group(1) if match else ""), output


def _finish(
    name: str,
    result: subprocess.CompletedProcess | None,
    *,
    executable: str = "",
    location: str,
    host: str = "",
    container: str = "",
    error: str = "",
) -> dict[str, str]:
    info = empty()
    info.update(
        name=name,
        executable=executable,
        location=location,
        host=host,
        container=container,
        collected_at=now_iso(),
    )
    if result is not None:
        raw = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        version, output = parse_version_output(name, raw)
        info["version"] = version
        info["version_output"] = output
        if result.returncode != 0:
            error = error or f"version command exited {result.returncode}"
        elif not version:
            error = error or "version not found in output"
    info["error"] = error[:240]
    return info


def collect_local(name: str, *, runner: Runner = subprocess.run) -> dict[str, str]:
    name = normalize_name(name)
    if not name:
        return _finish("", None, location="local", error="unsupported agent client")
    executable = shutil.which(name) or ""
    if not executable:
        return _finish(name, None, location="local", error=f"{name} not found in PATH")
    try:
        result = runner([executable, "--version"], capture_output=True, text=True, timeout=12)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _finish(name, None, executable=executable, location="local", error=str(exc))
    return _finish(name, result, executable=executable, location="local")


def _probe_script(name: str) -> str:
    # name is normalized against SUPPORTED before interpolation.
    return (
        f"p=$(command -v {name} 2>/dev/null || true); "
        "printf 'DT_AGENT_BIN=%s\\n' \"$p\"; "
        "printf 'DT_AGENT_VERSION_BEGIN\\n'; "
        "if [ -n \"$p\" ]; then \"$p\" --version 2>&1; rc=$?; else rc=127; fi; "
        "printf 'DT_AGENT_VERSION_END\\n'; exit $rc"
    )


def collect_remote(
    name: str,
    ssh_argv: list[str],
    *,
    host: str = "",
    container: str = "",
    runner: Runner = subprocess.run,
) -> dict[str, str]:
    name = normalize_name(name)
    location = "docker" if container else "ssh"
    if not name:
        return _finish("", None, location=location, host=host, container=container, error="unsupported agent client")
    script = _probe_script(name)
    remote_cmd = f"sh -lc {shlex.quote(script)}"
    if container:
        remote_cmd = f"docker exec {shlex.quote(container)} sh -lc {shlex.quote(script)}"
    try:
        result = runner([*ssh_argv, remote_cmd], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _finish(name, None, location=location, host=host, container=container, error=str(exc))
    lines = (result.stdout or "").splitlines()
    executable = ""
    for line in lines:
        if line.startswith("DT_AGENT_BIN="):
            executable = line.partition("=")[2]
            break
    try:
        begin = lines.index("DT_AGENT_VERSION_BEGIN") + 1
        end = lines.index("DT_AGENT_VERSION_END", begin)
        version_lines = lines[begin:end]
    except ValueError:
        version_lines = [line for line in lines if not line.startswith("DT_AGENT_")]
    if lines:
        result = subprocess.CompletedProcess(
            result.args,
            result.returncode,
            stdout="\n".join(version_lines),
            stderr=result.stderr,
        )
    return _finish(
        name,
        result,
        executable=executable,
        location=location,
        host=host,
        container=container,
    )


def collect(
    name: str,
    *,
    location: str = "local",
    ssh_argv: list[str] | None = None,
    host: str = "",
    container: str = "",
    runner: Runner = subprocess.run,
) -> dict[str, str]:
    if location in {"ssh", "docker"}:
        if not ssh_argv:
            return _finish(
                normalize_name(name),
                None,
                location=location,
                host=host,
                container=container,
                error="missing ssh target",
            )
        return collect_remote(name, ssh_argv, host=host, container=container, runner=runner)
    return collect_local(name, runner=runner)
