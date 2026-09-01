import json

import pytest

from dual_tmux import upgrade


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def release(url="https://github.com/yukai08008/dual-tmux/releases/download/v0.4.48.post1/dual_tmux-0.4.48.post1-py3-none-any.whl"):
    return {
        "tag_name": "v0.4.48.post1",
        "draft": False,
        "prerelease": False,
        "assets": [{"name": url.rsplit("/", 1)[-1], "browser_download_url": url}],
    }


def test_discover_latest_selects_repository_wheel():
    asset = upgrade.discover_latest(lambda _request, timeout: Response(release()))
    assert asset.version == "0.4.48.post1"
    assert asset.tag == "v0.4.48.post1"


def test_discover_latest_rejects_foreign_asset_host():
    payload = release("https://example.com/dual_tmux-0.4.48.post1-py3-none-any.whl")
    with pytest.raises(RuntimeError, match="no universal wheel"):
        upgrade.discover_latest(lambda _request, timeout: Response(payload))


def test_discover_latest_rejects_tag_asset_version_mismatch():
    payload = release()
    payload["tag_name"] = "v0.4.99"
    with pytest.raises(RuntimeError, match="no universal wheel"):
        upgrade.discover_latest(lambda _request, timeout: Response(payload))


def test_install_latest_forces_new_release_wheel(monkeypatch):
    asset = upgrade.ReleaseAsset(
        "0.4.48.post1",
        "v0.4.48.post1",
        "https://github.com/yukai08008/dual-tmux/releases/download/v0.4.48.post1/dual_tmux-0.4.48.post1-py3-none-any.whl",
    )
    monkeypatch.setattr(upgrade, "discover_latest", lambda: asset)
    calls = []

    class Result:
        returncode = 0

    upgrade.install_latest("0.4.48", lambda argv, **kwargs: calls.append(argv) or Result())
    assert calls == [["uv", "tool", "install", "--force", asset.url]]


def test_install_latest_skips_same_version(monkeypatch):
    asset = upgrade.ReleaseAsset("0.4.48", "v0.4.48", "https://github.com/unused")
    monkeypatch.setattr(upgrade, "discover_latest", lambda: asset)
    calls = []
    assert upgrade.install_latest("0.4.48", lambda *args, **kwargs: calls.append(args)) == asset
    assert calls == []


def test_install_latest_never_downgrades_post_release(monkeypatch):
    asset = upgrade.ReleaseAsset("0.4.48", "v0.4.48", "https://github.com/unused")
    monkeypatch.setattr(upgrade, "discover_latest", lambda: asset)
    calls = []
    assert upgrade.install_latest("0.4.48.post1", lambda *args, **kwargs: calls.append(args)) == asset
    assert calls == []
