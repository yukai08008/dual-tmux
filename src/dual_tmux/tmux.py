from __future__ import annotations

import shutil
import subprocess
import time


def have_tmux() -> bool:
    return shutil.which("tmux") is not None


def has_session(name: str) -> bool:
    r = subprocess.run(["tmux", "has-session", "-t", name], capture_output=True)
    return r.returncode == 0


def ensure_session(name: str) -> None:
    if not have_tmux():
        raise SystemExit("[err] 未找到 tmux")
    if not has_session(name):
        subprocess.run(["tmux", "new", "-d", "-s", name], check=True)


def attach(name: str) -> None:
    ensure_session(name)
    subprocess.run(["tmux", "attach", "-t", name], check=False)


def pane_command(name: str) -> str:
    r = subprocess.run(
        ["tmux", "list-panes", "-t", name, "-F", "#{pane_current_command}"],
        capture_output=True,
        text=True,
    )
    return (r.stdout or "").splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""


def reconnect(name: str, cmd: str) -> None:
    ensure_session(name)
    current = pane_command(name)
    if current in {"ssh", "docker", "tmux"}:
        from .ui import skip

        skip(f"{name} already on the jump (cmd={current})")
        return
    subprocess.run(["tmux", "send-keys", "-t", name, "C-c"], check=False)
    time.sleep(0.2)
    subprocess.run(["tmux", "send-keys", "-t", name, cmd, "Enter"], check=False)
    from .ui import ok

    ok(f"resent {name} <- {cmd}")


def send_keys(name: str, text: str) -> None:
    if not has_session(name):
        raise SystemExit(f"[err] 无此会话: {name}")
    subprocess.run(["tmux", "send-keys", "-t", name, "--", text, "Enter"], check=False)


def start_opencode(name: str, extra: str = "") -> None:
    ensure_session(name)
    current = pane_command(name)
    if current == "opencode":
        return
    cmd = "opencode" if not extra else extra
    subprocess.run(["tmux", "send-keys", "-t", name, "--", cmd, "Enter"], check=False)


def ensure_agent(name: str, cmd: str) -> bool:
    """Start cmd if pane is not already opencode. Return True if a command was sent."""
    ensure_session(name)
    if pane_command(name) == "opencode":
        return False
    subprocess.run(["tmux", "send-keys", "-t", name, "--", cmd, "Enter"], check=False)
    return True
