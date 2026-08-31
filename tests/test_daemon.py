from dual_tmux.config import AppConfig, write_config
from dual_tmux.daemon import ConnectorManager, DualTmuxDaemon, read_daemon_status
from dual_tmux.feishu import CredentialVault


class FakeProcess:
    def __init__(self):
        self.alive = False
        self.exitcode = None
        self.terminated = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False
        self.exitcode = -15

    def join(self, timeout=None):
        return None


def test_manager_starts_only_for_installation_and_stops_on_unbind(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    made = []

    def factory():
        item = FakeProcess()
        made.append(item)
        return item

    manager = ConnectorManager(
        process_factory=factory,
        clock=lambda: 100.0,
        lease_acquire=lambda: (True, "tm_test"),
        lease_release=lambda: None,
    )
    assert manager.step()["connector"] == "stopped"
    CredentialVault().save("cli_auto", "secret", {"open_id": "ou_a"})
    assert manager.step()["connector"] == "starting"
    assert manager.step()["connector"] == "connected"
    CredentialVault().remove()
    assert manager.step()["connector"] == "stopped"
    assert made[0].terminated is True


def test_manager_uses_bounded_restart_backoff(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    CredentialVault().save("cli_auto", "secret")
    now = [100.0]
    made = []

    def factory():
        item = FakeProcess()
        made.append(item)
        return item

    manager = ConnectorManager(
        process_factory=factory,
        clock=lambda: now[0],
        lease_acquire=lambda: (True, "tm_test"),
        lease_release=lambda: None,
    )
    manager.step()
    made[0].alive = False
    made[0].exitcode = 1
    state = manager.step()
    assert state["connector"] == "backoff"
    assert state["next_retry_at"] == 105
    now[0] = 105
    assert manager.step()["connector"] == "starting"


def test_daemon_once_writes_stopped_status(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    DualTmuxDaemon(
        manager=ConnectorManager(
            process_factory=FakeProcess,
            lease_acquire=lambda: (True, "tm_test"),
            lease_release=lambda: None,
        )
    ).run(once=True)
    status = read_daemon_status()
    assert status["running"] is False
    assert status["connector"] == "stopped"


def test_manager_stays_standby_when_another_owner_holds_lease(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    CredentialVault().save("cli_auto", "secret")
    manager = ConnectorManager(
        process_factory=FakeProcess,
        lease_acquire=lambda: (False, "tom7r"),
        lease_release=lambda: None,
    )
    state = manager.step()
    assert state["connector"] == "standby"
    assert state["owner"] == "tom7r"
    assert manager.process is None


def test_hub_mode_client_never_starts_local_ws(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_laptop", server="tom7r", user="andy"))
    CredentialVault().save("cli_auto", "secret")
    manager = ConnectorManager(
        process_factory=FakeProcess,
        lease_acquire=lambda: (True, "tm_laptop"),
        lease_release=lambda: None,
    )
    state = manager.step()
    assert state == {
        "connector": "standby",
        "owner": "tom7r",
        "failures": 0,
        "next_retry_at": 0,
    }
    assert manager.process is None


def test_explicit_hub_role_starts_ws_without_client_lease(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    monkeypatch.setenv("DT_FEISHU_ROLE", "hub")
    CredentialVault().save("cli_auto", "secret")
    manager = ConnectorManager(
        process_factory=FakeProcess,
        lease_acquire=lambda: (False, "another-client"),
        lease_release=lambda: None,
    )
    assert manager.step() == {
        "connector": "starting",
        "owner": "hub",
        "failures": 0,
        "next_retry_at": 0,
    }
    assert manager.process is not None
