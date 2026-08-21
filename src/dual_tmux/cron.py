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


def line() -> str:
    return f"* * * * * {dt_bin()} tick >/dev/null 2>&1"


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
    if installed():
        return False
    body = current().rstrip()
    extra = line()
    text = f"{body}\n{extra}\n" if body else f"{extra}\n"
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
