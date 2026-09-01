"""Upgrade a GitHub Release wheel even when uv pinned the previous asset URL."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass

LATEST_RELEASE_API = "https://api.github.com/repos/yukai08008/dual-tmux/releases/latest"
RELEASE_PATH = "/yukai08008/dual-tmux/releases/download/"
WHEEL = re.compile(r"^dual_tmux-(?P<version>.+)-py3-none-any\.whl$")
VERSION = re.compile(r"^(?P<base>\d+\.\d+\.\d+)(?:\.post(?P<post>\d+))?$")


@dataclass(frozen=True)
class ReleaseAsset:
    version: str
    tag: str
    url: str


def discover_latest(opener=urllib.request.urlopen) -> ReleaseAsset:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "dual-tmux-upgrade",
        },
    )
    with opener(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("draft") or payload.get("prerelease"):
        raise RuntimeError("GitHub latest release is not stable")
    tag = str(payload.get("tag_name") or "")
    for item in payload.get("assets") or []:
        name = str(item.get("name") or "")
        match = WHEEL.fullmatch(name)
        if not match:
            continue
        version = match.group("version")
        if tag != f"v{version}" or not VERSION.fullmatch(version):
            continue
        url = str(item.get("browser_download_url") or "")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "github.com":
            continue
        if not parsed.path.startswith(RELEASE_PATH) or f"/{tag}/" not in parsed.path:
            continue
        return ReleaseAsset(version, tag, url)
    raise RuntimeError("latest dual-tmux release has no universal wheel")


def install_latest(current: str, runner=subprocess.run) -> ReleaseAsset:
    asset = discover_latest()
    current_match = VERSION.fullmatch(current)
    latest_match = VERSION.fullmatch(asset.version)
    if current_match and latest_match:
        current_key = tuple(int(part) for part in current_match.group("base").split(".")) + (
            int(current_match.group("post") or 0),
        )
        latest_key = tuple(int(part) for part in latest_match.group("base").split(".")) + (
            int(latest_match.group("post") or 0),
        )
        if latest_key <= current_key:
            return asset
    elif asset.version == current:
        return asset
    result = runner(
        ["uv", "tool", "install", "--force", asset.url],
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return asset
