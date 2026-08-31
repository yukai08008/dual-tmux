
import pytest

from dual_tmux.control import ControlResult
from dual_tmux.feishu import (
    AppRegistrationService,
    CredentialVault,
    FeishuCommand,
    FeishuConfig,
    FeishuDispatcher,
    FeishuError,
    OperatorIdentity,
    PairingService,
    _StateStore,
    bind_operator,
    feishu_dir,
    list_bindings,
    load_app_secret,
    parse_command,
    save_config,
    status,
    unbind_operator,
    uninstall,
)


@pytest.fixture
def dt_home(monkeypatch, tmp_path):
    root = tmp_path / "dt-home"
    monkeypatch.setenv("DUAL_TMUX_HOME", str(root))
    monkeypatch.delenv("DT_FEISHU_APP_SECRET", raising=False)
    return root


def config(tmp_path, **changes):
    values = {
        "app_id": "cli_app",
        "redirect_uri": "https://hub.example/feishu/callback",
        "secret_file": "",
        "allowlist": (),
    }
    values.update(changes)
    return FeishuConfig(**values)


def test_config_is_mode_0600_and_secret_is_never_persisted(dt_home, monkeypatch, tmp_path):
    monkeypatch.setenv("DT_FEISHU_APP_SECRET", "env-secret")
    path = save_config(config(tmp_path))
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert "env-secret" not in path.read_text()
    assert load_app_secret(config(tmp_path)) == "env-secret"
    assert status()["secret_source"] == "env"


def test_secret_file_must_be_exactly_0600(dt_home, tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("file-secret\n")
    secret.chmod(0o600)
    cfg = config(tmp_path, secret_file=str(secret))
    assert load_app_secret(cfg) == "file-secret"
    secret.chmod(0o640)
    with pytest.raises(FeishuError) as caught:
        load_app_secret(cfg)
    assert caught.value.code == "secret_permissions"
    secret.chmod(0o600)
    link = tmp_path / "secret-link"
    link.symlink_to(secret)
    with pytest.raises(FeishuError) as caught:
        load_app_secret(config(tmp_path, secret_file=str(link)))
    assert caught.value.code == "secret_permissions"


class FakeOAuth:
    def __init__(self, identity=None):
        self.identity = identity or OperatorIdentity(open_id="ou_ok", union_id="on_ok", name="Andy")
        self.calls = []

    def exchange(self, cfg, secret, code):
        self.calls.append((cfg.app_id, secret, code))
        return self.identity


def test_pairing_state_is_hashed_one_time_and_callback_binds(dt_home, monkeypatch, tmp_path):
    monkeypatch.setenv("DT_FEISHU_APP_SECRET", "secret")
    cfg = config(tmp_path, allowlist=("on_ok",))
    clock = [1000.0]
    store = _StateStore(clock=lambda: clock[0])
    oauth = FakeOAuth()
    pairing = PairingService(store=store, transport=oauth)
    started = pairing.begin(cfg, ttl=60)
    raw = started["state"]
    assert started["authorization_url"].startswith(
        "https://accounts.feishu.cn/open-apis/authen/v1/authorize?"
    )
    state_text = (feishu_dir() / "state.json").read_text()
    assert len(raw) >= 40
    assert raw not in state_text
    identity = pairing.callback(raw, "oauth-code", cfg)
    assert identity.union_id == "on_ok"
    assert oauth.calls == [("cli_app", "secret", "oauth-code")]
    assert list_bindings()[0].open_id == "ou_ok"
    with pytest.raises(FeishuError) as caught:
        pairing.callback(raw, "again", cfg)
    assert caught.value.code == "invalid_state"
    assert "secret" not in (feishu_dir() / "bindings.json").read_text()
    assert "oauth-code" not in (feishu_dir() / "bindings.json").read_text()


def test_pairing_expiry_and_allowlist_fail_closed(dt_home, monkeypatch, tmp_path):
    monkeypatch.setenv("DT_FEISHU_APP_SECRET", "secret")
    clock = [1000.0]
    store = _StateStore(clock=lambda: clock[0])
    pairing = PairingService(store=store, transport=FakeOAuth())
    started = pairing.begin(config(tmp_path), ttl=30)
    clock[0] += 31
    with pytest.raises(FeishuError) as caught:
        pairing.callback(started["state"], "code", config(tmp_path))
    assert caught.value.code == "invalid_state"

    started = pairing.begin(config(tmp_path), ttl=30)
    with pytest.raises(FeishuError) as caught:
        pairing.callback(started["state"], "code", config(tmp_path, allowlist=("nobody",)))
    assert caught.value.code == "operator_not_allowed"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/dt ls", FeishuCommand("ls")),
        ("/dt show demo", FeishuCommand("show", "demo")),
        ("/dt send demo hello  world", FeishuCommand("send", "demo", "hello  world")),
        ("/dt drop demo abc", FeishuCommand("drop", "demo", token="abc")),
    ],
)
def test_command_parser(raw, expected):
    assert parse_command(raw) == expected


@pytest.mark.parametrize(
    "raw", ["ls", "/dt", "/dt upgrade", "/dt hotfix", "/dt cron", "/dt shell", "/dt ssh", "/dt config", "/dt nonsense"]
)
def test_forbidden_or_invalid_commands_are_rejected(raw):
    with pytest.raises(FeishuError):
        parse_command(raw)


class FakeControl:
    def __init__(self):
        self.calls = []

    def _result(self, operation, *args):
        self.calls.append((operation, *args))
        return ControlResult(operation, {"args": args}, f"control.{operation}")

    def list_tunnels(self): return self._result("tunnel.list")
    def get_tunnel(self, name): return self._result("tunnel.get", name)
    def send(self, name, text, side): return self._result("pane.send", name, text, side)
    def probe_health(self, name): return self._result("health.probe", name)
    def freeze(self, name, sides, tool): return self._result("session.freeze", name, sides, tool)
    def resume(self, name, force): return self._result("session.resume", name, force)
    def recover(self, name, force=False): return self._result("health.recover", name, force)
    def drop(self, name, confirm=""): return self._result("tunnel.drop", name, confirm)
    def remove_tunnel(self, name, confirm="", kill=False): return self._result("tunnel.remove", name, confirm, kill)


def test_dispatch_requires_binding_rejects_replay_and_delegates(dt_home):
    identity = OperatorIdentity(open_id="ou_operator")
    service = FakeControl()
    dispatcher = FeishuDispatcher(service)
    with pytest.raises(FeishuError) as caught:
        dispatcher.dispatch("evt-1", identity, "/dt ls")
    assert caught.value.code == "operator_unbound"
    bind_operator(identity)
    result = dispatcher.dispatch("evt-2", identity, "/dt send demo hello there")
    assert result["ok"] is True
    assert service.calls == [("pane.send", "demo", "hello there", "bullet")]
    with pytest.raises(FeishuError) as caught:
        dispatcher.dispatch("evt-2", identity, "/dt ls")
    assert caught.value.code == "event_replayed"


def test_dispatch_reapplies_configured_allowlist(dt_home):
    identity = OperatorIdentity(open_id="ou_operator")
    bind_operator(identity)
    save_config(
        FeishuConfig(
            app_id="cli_app",
            redirect_uri="https://hub.example/callback",
            allowlist=("someone-else",),
        )
    )
    with pytest.raises(FeishuError) as caught:
        FeishuDispatcher(FakeControl()).dispatch("evt-1", identity, "/dt ls")
    assert caught.value.code == "operator_unbound"


def test_destructive_confirmation_is_bound_one_time_and_targeted(dt_home):
    identity = OperatorIdentity(user_id="u1")
    other = OperatorIdentity(user_id="u2")
    bind_operator(identity)
    bind_operator(other)
    service = FakeControl()
    dispatcher = FeishuDispatcher(service)
    challenge = dispatcher.dispatch("evt-1", identity, "/dt drop demo")
    token = challenge["token"]
    assert challenge["confirmation_required"] is True
    with pytest.raises(FeishuError) as caught:
        dispatcher.dispatch("evt-2", other, f"/dt drop demo {token}")
    assert caught.value.code == "confirmation_invalid"
    done = dispatcher.dispatch("evt-3", identity, f"/dt drop demo {token}")
    assert done["ok"] is True
    assert service.calls == [("tunnel.drop", "demo", "demo")]
    with pytest.raises(FeishuError) as caught:
        dispatcher.dispatch("evt-4", identity, f"/dt drop demo {token}")
    assert caught.value.code == "confirmation_invalid"


def test_unbind_and_audit_do_not_log_message_body(dt_home):
    identity = OperatorIdentity(open_id="ou1")
    bind_operator(identity)
    dispatcher = FeishuDispatcher(FakeControl())
    dispatcher.dispatch("evt-secret", identity, "/dt send demo TOP-SECRET-BODY")
    assert unbind_operator("ou1") == 1
    assert not list_bindings()
    events = (dt_home / "events.jsonl").read_text()
    assert "TOP-SECRET-BODY" not in events
    assert "evt-secret" not in events


class FakeRegistration:
    def __init__(self):
        self.polls = 0

    def begin(self):
        return {
            "device_code": "DEVICE-SECRET",
            "verification_uri_complete": "https://accounts.feishu.cn/device?user_code=abc",
            "expires_in": 600,
            "interval": 1,
        }

    def poll(self, device_code):
        assert device_code == "DEVICE-SECRET"
        self.polls += 1
        if self.polls == 1:
            return {"error": "authorization_pending"}
        return {
            "client_id": "cli_auto",
            "client_secret": "APP-SECRET-NEVER-PLAIN",
            "user_info": {"open_id": "ou_installer", "tenant_brand": "feishu"},
        }


def test_scan_registration_encrypts_generated_credentials(dt_home):
    clock = [1000.0]
    service = AppRegistrationService(
        transport=FakeRegistration(), clock=lambda: clock[0]
    )
    started = service.begin()
    assert started["status"] == "pending"
    assert "DEVICE-SECRET" in (feishu_dir() / "registration.json").read_text()
    assert service.poll() == {"status": "pending"}
    clock[0] += 1
    completed = service.poll()
    assert completed["status"] == "installed"
    installation = feishu_dir() / "installation.json"
    key = feishu_dir() / "credential.key"
    assert oct(installation.stat().st_mode & 0o777) == "0o600"
    assert oct(key.stat().st_mode & 0o777) == "0o600"
    assert "APP-SECRET-NEVER-PLAIN" not in installation.read_text()
    assert CredentialVault().load()["app_secret"] == "APP-SECRET-NEVER-PLAIN"
    assert list_bindings()[0].open_id == "ou_installer"


def test_registration_expires_without_persisting_credentials(dt_home):
    clock = [1000.0]
    service = AppRegistrationService(
        transport=FakeRegistration(), clock=lambda: clock[0]
    )
    service.begin()
    clock[0] += 601
    assert service.poll() == {"status": "expired"}
    assert not (feishu_dir() / "installation.json").exists()


class EmptyRegistration(FakeRegistration):
    def poll(self, device_code):
        assert device_code == "DEVICE-SECRET"
        return {}


def test_empty_registration_poll_remains_pending(dt_home):
    clock = [1000.0]
    service = AppRegistrationService(
        transport=EmptyRegistration(), clock=lambda: clock[0]
    )
    service.begin()
    assert service.poll() == {"status": "pending"}
    assert (feishu_dir() / "registration.json").is_file()
    assert not (feishu_dir() / "installation.json").exists()


class IncompleteRegistration(FakeRegistration):
    def poll(self, device_code):
        assert device_code == "DEVICE-SECRET"
        return {"client_id": "cli_auto"}


def test_incomplete_registration_credentials_fail_closed(dt_home):
    service = AppRegistrationService(transport=IncompleteRegistration())
    service.begin()
    assert service.poll() == {
        "status": "rejected",
        "reason": "incomplete_credentials",
    }
    assert not (feishu_dir() / "registration.json").exists()
    assert not (feishu_dir() / "installation.json").exists()


def test_hub_uninstall_failure_preserves_local_installation(
    dt_home, monkeypatch
):
    from dual_tmux import feishu_bridge
    from dual_tmux.config import AppConfig, write_config

    write_config(AppConfig(client="tm_laptop", server="tom7r", user="andy"))
    CredentialVault().save("cli_auto", "APP-SECRET", {"open_id": "ou_a"})
    bind_operator(OperatorIdentity(open_id="ou_a"))

    def fail_remove(cfg):
        raise FeishuError("hub_unbind_failed", "Hub unavailable")

    monkeypatch.setattr(feishu_bridge, "remove_installation_from_hub", fail_remove)
    with pytest.raises(FeishuError) as caught:
        uninstall()
    assert caught.value.code == "hub_unbind_failed"
    assert CredentialVault().load()["app_secret"] == "APP-SECRET"
    assert list_bindings()[0].open_id == "ou_a"
