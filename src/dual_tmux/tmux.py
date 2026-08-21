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
        print(f"[skip] {name} 已在链路中 (cmd={current})")
        return
    subprocess.run(["tmux", "send-keys", "-t", name, "C-c"], check=False)
    time.sleep(0.2)
    subprocess.run(["tmux", "send-keys", "-t", name, cmd, "Enter"], check=False)
    print(f"[ok] 已重打: {name} <- {cmd}")


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
