from pathlib import Path

from dual_tmux.config import write_config, AppConfig
from dual_tmux.health import collect_checks, probe_ssh


def test_missing_config(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("dual_tmux.cron.installed", lambda: False)
    cfg, checks = collect_checks()
    assert cfg is None
    labels = {c.label: c for c in checks}
    assert labels["config"].ok is False
    assert "config --init" in labels["config"].hint


def test_config_without_ssh(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    monkeypatch.setenv("DUAL_TMUX_HOME", str(home))
    write_config(AppConfig(client="tm_laptop", server="ghost-host", user="ouc", workspace="/workspace"))

    def fake_run(*_args, **_kwargs):
        class R:
            returncode = 255
            stdout = ""
            stderr = "Permission denied (publickey).\n"

        return R()

    monkeypatch.setattr("dual_tmux.health.subprocess.run", fake_run)
    monkeypatch.setattr("dual_tmux.cron.installed", lambda: False)
    _, checks = collect_checks()
    ssh = next(c for c in checks if c.label == "ssh server")
    assert ssh.ok is False
    assert "never writes SSH" in ssh.hint


def test_probe_ssh_ok(monkeypatch):
    def fake_run(*_args, **_kwargs):
        class R:
            returncode = 0
            stdout = "ok\n"
            stderr = ""

        return R()

    monkeypatch.setattr("dual_tmux.health.subprocess.run", fake_run)
    check = probe_ssh("myserver")
    assert check.ok
    assert check.detail == "myserver"