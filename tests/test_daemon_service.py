from dual_tmux.daemon_service import launchd_text, systemd_text


def test_launchd_service_is_independent_and_kept_alive(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    text = launchd_text("/opt/dt")
    assert "<string>/opt/dt</string><string>daemon</string>" in text
    assert "<key>KeepAlive</key><true/>" in text
    assert "dt web" not in text


def test_systemd_service_restarts_daemon_not_web():
    text = systemd_text("/opt/dt")
    assert "ExecStart=/opt/dt daemon" in text
    assert "Restart=always" in text
    assert "dt web" not in text
