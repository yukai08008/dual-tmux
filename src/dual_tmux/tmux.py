from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time

FALLBACK_BINS = ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux", "/usr/bin/tmux")
SHELL_COMMANDS = {"bash", "csh", "dash", "fish", "ksh", "sh", "tcsh", "zsh"}


def exact_session(name: str) -> str:
    """Return a tmux session target that disables implicit prefix matching.

    Without the leading ``=``, targeting ``op_a`` may select
    ``op_alex_serp`` when the shorter session does not currently exist.  That
    is especially dangerous for fencing, where cleaning one tunnel could
    otherwise kill an unrelated longer-named session.
    """
    return f"={name}"


def exact_pane(name: str) -> str:
    """Return the active pane of an exactly named session."""
    return f"={name}:"


def bin() -> str:
    """Resolve the tmux binary; cron/launchd run with a minimal PATH."""
    found = shutil.which("tmux")
    if found:
        return found
    for cand in FALLBACK_BINS:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return "tmux"


def have_tmux() -> bool:
    return bin() != "tmux" or shutil.which("tmux") is not None


def has_session(name: str) -> bool:
    r = subprocess.run(
        [bin(), "has-session", "-t", exact_session(name)],
        capture_output=True,
        check=False,
    )
    return r.returncode == 0


def attached_clients(name: str) -> int | None:
    """Return attached client count, or None when tmux cannot answer."""
    if not name:
        return 0
    result = subprocess.run(
        [bin(), "list-clients", "-t", exact_session(name), "-F", "#{client_pid}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 1 and "no current client" in (result.stderr or "").lower():
        return 0
    if result.returncode != 0:
        return None
    return len([line for line in result.stdout.splitlines() if line.strip()])


def kill_session(name: str) -> bool:
    if not name or not has_session(name):
        return False
    subprocess.run([bin(), "kill-session", "-t", exact_session(name)], check=False)
    return True


def quit_opencode(name: str) -> bool:
    if pane_command(name) != "opencode":
        return False
    target = exact_pane(name)
    subprocess.run([bin(), "send-keys", "-t", target, "Escape"], check=False)
    time.sleep(0.15)
    subprocess.run([bin(), "send-keys", "-t", target, "C-x", "q"], check=False)
    deadline = time.time() + 8
    while time.time() < deadline:
        if pane_command(name) != "opencode":
            return True
        time.sleep(0.25)
    subprocess.run([bin(), "send-keys", "-t", target, "C-c"], check=False)
    time.sleep(0.2)
    return pane_command(name) != "opencode"


def drop_session(name: str) -> bool:
    if not name or not has_session(name):
        return False
    subprocess.run(
        [bin(), "detach-client", "-s", exact_session(name)],
        capture_output=True,
        check=False,
    )
    return kill_session(name)


def ensure_session(name: str, cwd: str = "") -> None:
    if not have_tmux():
        raise SystemExit("[err] 未找到 tmux")
    if not has_session(name):
        cmd = [bin(), "new", "-d", "-s", name]
        if cwd:
            cmd.extend(["-c", cwd])
        subprocess.run(cmd, check=True)
        subprocess.run([bin(), "set-option", "-t", name, "history-limit", "10000"], check=False)


def ensure_session_cwd(name: str, cwd: str) -> bool:
    """Create at cwd, or align an existing idle shell without touching a program.

    Returns whether the pane is at the requested directory. A running Agent or
    any other foreground program is preserved and returns False.
    """
    wanted = os.path.realpath(os.path.expanduser(cwd))
    ensure_session(name, cwd=wanted)
    info = pane_info(name)
    raw_current = info.get("cwd") or ""
    current = os.path.realpath(raw_current) if raw_current else ""
    if current == wanted:
        return True
    command = os.path.basename(info.get("cmd") or "")
    if command not in SHELL_COMMANDS:
        return False
    target = exact_pane(name)
    subprocess.run([bin(), "send-keys", "-t", target, "C-c"], check=False)
    time.sleep(0.05)
    subprocess.run(
        [bin(), "send-keys", "-t", target, "--", f"cd {shlex.quote(wanted)}", "Enter"],
        check=False,
    )
    deadline = time.time() + 2
    while time.time() < deadline:
        raw_current = pane_info(name).get("cwd") or ""
        current = os.path.realpath(raw_current) if raw_current else ""
        if current == wanted:
            return True
        time.sleep(0.05)
    raise SystemExit(f"[err] {name} shell did not enter {wanted}")


def attach(name: str) -> None:
    ensure_session(name)
    subprocess.run([bin(), "attach", "-t", exact_session(name)], check=False)


def pane_info(name: str) -> dict[str, str]:
    r = subprocess.run(
        [
            bin(),
            "list-panes",
            "-t",
            exact_pane(name),
            "-F",
            "#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_title}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return {"pid": "", "cmd": "", "cwd": "", "title": ""}
    pid, cmd, cwd, title, *_ = (r.stdout.splitlines()[0] + "\t\t\t").split("\t")
    return {
        "pid": pid.strip(),
        "cmd": cmd.strip(),
        "cwd": cwd.strip(),
        "title": title.strip(),
    }


def capture_pane(name: str, start: int = -200) -> str:
    r = subprocess.run(
        [bin(), "capture-pane", "-t", exact_pane(name), "-p", "-S", str(start)],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout or ""


def pane_command(name: str) -> str:
    return pane_info(name).get("cmd") or ""


def wait_command(name: str, wanted: set[str], timeout: float = 20) -> str:
    deadline = time.time() + timeout
    current = pane_command(name)
    while time.time() < deadline:
        current = pane_command(name)
        if current in wanted:
            return current
        time.sleep(0.4)
    return current


def wait_stable_command(
    name: str, wanted: set[str], timeout: float = 20, stable_for: float = 0.8
) -> str:
    """Wait until a pane command remains wanted long enough to reject failed jumps."""
    deadline = time.time() + timeout
    current = pane_command(name)
    since = 0.0
    previous = ""
    while time.time() < deadline:
        current = pane_command(name)
        now = time.monotonic()
        if current in wanted:
            if current != previous:
                since = now
            if since and now - since >= stable_for:
                return current
        else:
            since = 0.0
        previous = current
        time.sleep(0.2)
    return current


def replay_hops(name: str, hops: list[dict]) -> None:
    ensure_session(name)
    for hop in hops:
        cmd = (hop.get("command") or "").strip()
        if not cmd:
            continue
        subprocess.run(
            [bin(), "send-keys", "-t", exact_pane(name), "--", cmd, "Enter"],
            check=False,
        )
        time.sleep(1.2)


def reconnect(name: str, cmd: str) -> None:
    ensure_session(name)
    current = pane_command(name)
    if current in {"ssh", "docker", "tmux"}:
        from .ui import skip

        skip(f"{name} already on the jump (cmd={current})")
        return
    target = exact_pane(name)
    subprocess.run([bin(), "send-keys", "-t", target, "C-c"], check=False)
    time.sleep(0.2)
    subprocess.run([bin(), "send-keys", "-t", target, cmd, "Enter"], check=False)
    from .ui import ok

    ok(f"resent {name} <- {cmd}")


def send_keys(name: str, text: str) -> None:
    if not has_session(name):
        raise SystemExit(f"[err] 无此会话: {name}")
    subprocess.run(
        [bin(), "send-keys", "-t", exact_pane(name), "--", text, "Enter"], check=False
    )


def start_opencode(name: str, extra: str = "") -> None:
    ensure_session(name)
    current = pane_command(name)
    if current == "opencode":
        return
    cmd = "opencode" if not extra else extra
    subprocess.run(
        [bin(), "send-keys", "-t", exact_pane(name), "--", cmd, "Enter"], check=False
    )


def ensure_agent(name: str, cmd: str, cwd: str = "") -> bool:
    """Start cmd unless the requested Agent already owns the pane."""
    from .agentclient import detect_name
    from .workpoint import walk_commands

    ensure_session(name, cwd=cwd)
    requested = detect_name([cmd])
    info = pane_info(name)
    current = info.get("cmd") or ""
    active = detect_name([current, *walk_commands(info.get("pid") or "")])
    if requested and active == requested:
        return False
    if cwd:
        current = pane_info(name).get("cwd") or ""
        if current.rstrip("/") != str(cwd).rstrip("/"):
            subprocess.run(
                [
                    bin(),
                    "send-keys",
                    "-t",
                    exact_pane(name),
                    "--",
                    f"cd {cwd}",
                    "Enter",
                ],
                check=False,
            )
            time.sleep(0.15)
    subprocess.run(
        [bin(), "send-keys", "-t", exact_pane(name), "--", cmd, "Enter"], check=False
    )
    return True
