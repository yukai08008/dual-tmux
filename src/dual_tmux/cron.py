from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


MARKER = "dt tick"


def dt_bin() -> str:
    found = shutil.which("dt")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "dt"
    if local.is_file():
        return str(local)
    return "dt"


CRON_PATH = "/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/bin:/usr/bin:/bin"


def line() -> str:
    # cron runs with a bare PATH (/usr/bin:/bin); tmux/ssh/rsync must be reachable.
    return f"* * * * * PATH={CRON_PATH} {dt_bin()} tick >/dev/null 2>&1"


def current() -> str:
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=8
        )
    except subprocess.TimeoutExpired:
        return ""
    return result.stdout or ""


def installed() -> bool:
    return any(MARKER in row and not row.strip().startswith("#") for row in current().splitlines())


def install() -> bool:
    rows = current().splitlines()
    wanted = line()
    if any(row.strip() == wanted for row in rows):
        return False
    kept = [row for row in rows if MARKER not in row]
    text = ("\n".join(kept).rstrip() + "\n" if kept else "") + wanted + "\n"
    result = subprocess.run(
        ["crontab", "-"], input=text, capture_output=True, text=True, timeout=8
    )
    if result.returncode != 0:
        err = (result.stderr or "crontab failed").strip().splitlines()
        raise SystemExit(f"[err] crontab: {err[-1] if err else 'failed'}")
    return True


def uninstall() -> bool:
    rows = [row for row in current().splitlines() if MARKER not in row]
    if len(rows) == len(current().splitlines()):
        return False
    text = ("\n".join(rows) + "\n") if rows else ""
    result = subprocess.run(
        ["crontab", "-"], input=text, capture_output=True, text=True, timeout=8
    )
    if result.returncode != 0:
        raise SystemExit("[err] crontab remove failed")
    return True
