import ast
import json
from importlib.metadata import version
from pathlib import Path

import pytest
import tomllib

from dual_tmux import __version__, upgrade


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()

    def geturl(self):
        return str(self.payload)


def test_cli_version_matches_package_metadata():
    assert __version__ == version("dual-tmux")


def test_source_version_markers_match():
    root = Path(__file__).resolve().parents[1]
    project_version = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    module = ast.parse(
        (root / "src/dual_tmux/__init__.py").read_text(encoding="utf-8")
    )
    marker = next(
        node.value.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )

    assert marker == project_version


def release(
    url="https://github.com/yukai08008/dual-tmux/releases/download/v0.4.48.post1/dual_tmux-0.4.48.post1-py3-none-any.whl",
):
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


def test_redirect_discovery_avoids_github_api_rate_limit():
    asset = upgrade.discover_latest_redirect(
        lambda request, timeout: Response(
            "https://github.com/yukai08008/dual-tmux/releases/tag/v0.4.53"
        )
    )
    assert asset.version == "0.4.53"
    assert asset.url.endswith("/v0.4.53/dual_tmux-0.4.53-py3-none-any.whl")


def test_install_latest_falls_back_to_redirect_on_api_failure(monkeypatch):
    monkeypatch.setattr(
        upgrade, "discover_latest", lambda: (_ for _ in ()).throw(OSError("403"))
    )
    asset = upgrade.ReleaseAsset("0.4.53", "v0.4.53", "https://github.com/wheel")
    monkeypatch.setattr(upgrade, "discover_latest_redirect", lambda: asset)
    calls = []

    class Result:
        returncode = 0

    assert (
        upgrade.install_latest(
            "0.4.51", lambda argv, **kw: calls.append(argv) or Result()
        )
        == asset
    )
    assert calls == [["uv", "tool", "install", "--force", asset.url]]


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

    upgrade.install_latest(
        "0.4.48", lambda argv, **kwargs: calls.append(argv) or Result()
    )
    assert calls == [["uv", "tool", "install", "--force", asset.url]]


def test_install_latest_skips_same_version(monkeypatch):
    asset = upgrade.ReleaseAsset("0.4.48", "v0.4.48", "https://github.com/unused")
    monkeypatch.setattr(upgrade, "discover_latest", lambda: asset)
    calls = []
    assert (
        upgrade.install_latest("0.4.48", lambda *args, **kwargs: calls.append(args))
        == asset
    )
    assert calls == []


def test_install_latest_never_downgrades_post_release(monkeypatch):
    asset = upgrade.ReleaseAsset("0.4.48", "v0.4.48", "https://github.com/unused")
    monkeypatch.setattr(upgrade, "discover_latest", lambda: asset)
    calls = []
    assert (
        upgrade.install_latest(
            "0.4.48.post1", lambda *args, **kwargs: calls.append(args)
        )
        == asset
    )
    assert calls == []
