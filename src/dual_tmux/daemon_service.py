"""Install the dt daemon under the native per-user service manager."""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from .paths import home_dir

LABEL = "cn.dual-tmux.daemon"


def dt_bin() -> str:
    return shutil.which("dt") or str(Path.home() / ".local" / "bin" / "dt")


def launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def systemd_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "dual-tmux.service"


def launchd_text(binary: str | None = None) -> str:
    binary = binary or dt_bin()
    log_dir = home_dir()
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{LABEL}</string>
<key>ProgramArguments</key><array><string>{binary}</string><string>daemon</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>{log_dir / 'daemon.log'}</string>
<key>StandardErrorPath</key><string>{log_dir / 'daemon.err.log'}</string>
</dict></plist>
'''


def systemd_text(binary: str | None = None) -> str:
    binary = binary or dt_bin()
    return f'''[Unit]
Description=dual-tmux daemon and Feishu WebSocket connector
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={binary} daemon
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
'''


def _run(argv: list[str]) -> None:
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "service manager failed").strip()
        raise SystemExit(f"[err] daemon service: {message}")


def install() -> Path:
    system = platform.system()
    if system == "Darwin":
        path = launchd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(launchd_text(), encoding="utf-8")
        subprocess.run(
            ["launchctl", "bootout", f"gui/{__import__('os').getuid()}", str(path)],
            capture_output=True,
            text=True,
        )
        _run(["launchctl", "bootstrap", f"gui/{__import__('os').getuid()}", str(path)])
        return path
    if system == "Linux":
        path = systemd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_text(), encoding="utf-8")
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", "dual-tmux.service"])
        return path
    raise SystemExit(f"[err] unsupported service manager on {system}")


def uninstall() -> bool:
    system = platform.system()
    path = launchd_path() if system == "Darwin" else systemd_path()
    if not path.exists():
        return False
    if system == "Darwin":
        _run(["launchctl", "bootout", f"gui/{__import__('os').getuid()}", str(path)])
    elif system == "Linux":
        _run(["systemctl", "--user", "disable", "--now", "dual-tmux.service"])
    path.unlink(missing_ok=True)
    return True
