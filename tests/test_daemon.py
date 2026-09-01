from dual_tmux.config import AppConfig, write_config
from dual_tmux.daemon import (
    ConnectorManager,
    DualTmuxDaemon,
    LocalConnectorLease,
    connector_fence_valid,
    read_daemon_status,
)
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
        "generation": 0,
        "failures": 0,
        "next_retry_at": 0,
    }
    assert manager.process is None


def test_explicit_hub_role_respects_single_owner_lease(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    monkeypatch.setenv("DT_FEISHU_ROLE", "hub")
    CredentialVault().save("cli_auto", "secret")
    manager = ConnectorManager(
        process_factory=FakeProcess,
        lease_acquire=lambda: (False, "another-client"),
        lease_release=lambda: None,
    )
    assert manager.step() == {
        "connector": "standby",
        "owner": "another-client",
        "generation": 0,
        "failures": 0,
        "next_retry_at": 0,
    }
    assert manager.process is None


def test_local_lease_allows_one_owner_and_increments_generation(tmp_path):
    path = tmp_path / "locks" / "__feishu_ws__"
    first = LocalConnectorLease(path)
    second = LocalConnectorLease(path)
    owned, owner, generation = first.claim()
    assert owned is True
    assert generation == 1
    assert second.claim() == (False, owner, 1)
    first.release()
    owned, replacement, generation = second.claim()
    assert owned is True
    assert replacement != owner
    assert generation == 2
    second.release()


def test_standby_status_does_not_overwrite_active_global_status(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    CredentialVault().save("cli_auto", "secret")
    active_manager = ConnectorManager(
        process_factory=FakeProcess,
        lease_acquire=lambda: (True, "active-instance", 3),
        lease_release=lambda: None,
    )
    standby_manager = ConnectorManager(
        process_factory=FakeProcess,
        lease_acquire=lambda: (False, "active-instance", 3),
        lease_release=lambda: None,
    )
    active = DualTmuxDaemon(manager=active_manager)
    standby = DualTmuxDaemon(manager=standby_manager)
    active._write_status(active_manager.step())
    standby._write_status(standby_manager.step())
    status = read_daemon_status()
    assert status["connector"] == "starting"
    assert status["owner"] == "active-instance"
    assert status["generation"] == 3
    assert {item["connector"] for item in status["candidates"]} == {
        "starting",
        "standby",
    }


def test_failover_message_fence_requires_same_owner_and_generation(
    monkeypatch, tmp_path
):
    from dual_tmux import hub

    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    monkeypatch.setenv("DT_FEISHU_TOPOLOGY", "client-failover")
    monkeypatch.setenv("DT_FEISHU_ROLE", "client")
    monkeypatch.setenv("DT_FEISHU_LEASE_OWNER", "tm_a:instance")
    monkeypatch.setenv("DT_FEISHU_GENERATION", "7")
    write_config(AppConfig(client="tm_a", server="tom7r", user="andy"))
    monkeypatch.setattr(
        hub,
        "claim_feishu_lease",
        lambda cfg, owner="": (True, owner, 7),
    )
    assert connector_fence_valid() is True
    monkeypatch.setattr(
        hub,
        "claim_feishu_lease",
        lambda cfg, owner="": (False, "tm_b:instance", 8),
    )
    assert connector_fence_valid() is False
