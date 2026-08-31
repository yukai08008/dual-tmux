import json
import shutil
import threading
from urllib.request import Request, urlopen

import pytest

from dual_tmux.config import AppConfig
from dual_tmux.control import ControlResult
from dual_tmux.feishu import (
    FeishuConfig,
    FeishuDispatcher,
    FeishuError,
    OperatorIdentity,
    _StateStore,
    bind_operator,
)
from dual_tmux.feishu_bridge import (
    BridgeApplication,
    BridgeHandler,
    BridgeHTTPServer,
    BridgeStore,
    _read_envelope,
    sync_client,
)


@pytest.fixture
def dt_home(monkeypatch, tmp_path):
    root = tmp_path / "home"
    monkeypatch.setenv("DUAL_TMUX_HOME", str(root))
    return root


class FakeOAuth:
    def exchange(self, config, secret, code):
        assert secret == "secret"
        assert code == "code"
        return OperatorIdentity(open_id="ou_a", union_id="on_a", name="Andy")


class FakeReply:
    def __init__(self):
        self.calls = []

    def reply(self, config, secret, message_id, text):
        self.calls.append((secret, message_id, text))


def test_bridge_store_registers_only_hashes_and_routes(dt_home, tmp_path):
    store = BridgeStore(tmp_path / "spool", clock=lambda: 100)
    path = store.register_pairing("RAW-STATE", "tm_laptop", 200)
    assert "RAW-STATE" not in path.name
    assert "RAW-STATE" not in path.read_text()
    assert store.consume_pairing("RAW-STATE") == "tm_laptop"
    with pytest.raises(FeishuError) as caught:
        store.consume_pairing("RAW-STATE")
    assert caught.value.code == "invalid_state"

    identity = OperatorIdentity(open_id="ou_secret_id", union_id="on_secret_id")
    store.register_routes(identity, "tm_laptop")
    all_text = "".join(path.read_text() for path in (tmp_path / "spool" / "routes").glob("*.json"))
    assert "ou_secret_id" not in all_text
    assert "on_secret_id" not in all_text
    assert store.client_for(identity) == "tm_laptop"


def test_bridge_callback_routes_identity_to_client(dt_home, monkeypatch, tmp_path):
    monkeypatch.setenv("DT_FEISHU_APP_SECRET", "secret")
    store = BridgeStore(tmp_path / "spool", clock=lambda: 100)
    store.register_pairing("state", "tm_laptop", 200)
    app = BridgeApplication(
        store=store,
        oauth=FakeOAuth(),
        config=FeishuConfig("cli_app", "https://hub/callback"),
    )
    identity = app.callback("state", "code")
    assert identity.open_id == "ou_a"
    callback = next((tmp_path / "spool" / "callbacks" / "tm_laptop").glob("*.json"))
    payload = _read_envelope(callback)
    assert payload["identity"]["union_id"] == "on_a"
    assert payload["state_digest"] and "state" not in payload["state_digest"]
    assert store.client_for(identity) == "tm_laptop"


def test_bridge_event_verification_and_command_routing(dt_home, monkeypatch, tmp_path):
    monkeypatch.setenv("DT_FEISHU_VERIFICATION_TOKEN", "verify")
    store = BridgeStore(tmp_path / "spool")
    identity = OperatorIdentity(open_id="ou_a")
    store.register_routes(identity, "tm_laptop")
    app = BridgeApplication(
        store=store,
        config=FeishuConfig("cli_app", "https://hub/callback"),
    )
    assert app.event({"type": "url_verification", "token": "verify", "challenge": "abc"}) == {"challenge": "abc"}
    with pytest.raises(FeishuError) as caught:
        app.event({"type": "url_verification", "token": "wrong", "challenge": "abc"})
    assert caught.value.code == "verification_failed"

    payload = {
        "token": "verify",
        "header": {"event_id": "evt-1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_a"}},
            "message": {
                "message_id": "om_1",
                "message_type": "text",
                "mentions": [{"key": "@_user_1"}],
                "content": json.dumps({"text": "@_user_1 /dt ls"}),
            },
        },
    }
    assert app.event(payload) == {"ok": True}
    command = next((tmp_path / "spool" / "commands" / "tm_laptop").glob("*.json"))
    assert _read_envelope(command)["text"] == "/dt ls"


def test_bridge_http_health_and_url_verification(dt_home, monkeypatch, tmp_path):
    monkeypatch.setenv("DT_FEISHU_VERIFICATION_TOKEN", "verify")
    app = BridgeApplication(
        store=BridgeStore(tmp_path / "spool"),
        config=FeishuConfig("cli_app", "https://hub/callback"),
    )
    server = BridgeHTTPServer(("127.0.0.1", 0), BridgeHandler)
    server.application = app
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"
    try:
        assert json.load(urlopen(root + "/health", timeout=3))["ok"] is True
        request = Request(
            root + "/feishu/events",
            data=json.dumps({"type": "url_verification", "token": "verify", "challenge": "xyz"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert json.load(urlopen(request, timeout=3)) == {"challenge": "xyz"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class FakeControl:
    def list_tunnels(self):
        return ControlResult("tunnel.list", [{"name": "dt-demo"}], "audit.list")


def test_sync_client_processes_command_once_and_writes_response(dt_home, monkeypatch, tmp_path):
    from dual_tmux import hub

    remote = tmp_path / "remote"
    remote_base = remote / "feishu" / "bridge"
    identity = OperatorIdentity(open_id="ou_a")
    bind_operator(identity)
    BridgeStore(remote_base).enqueue(
        "tm_laptop",
        "commands",
        "evt-1",
        {
            "event_id": "evt-1",
            "message_id": "om_1",
            "identity": identity.public_dict(),
            "text": "/dt ls",
        },
    )
    cfg = AppConfig(client="tm_laptop", server="tom7r", user="andy")

    class Result:
        returncode = 0
        stderr = stdout = ""

    monkeypatch.setattr(hub, "_run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(hub, "remote_root", lambda cfg: "/remote")

    def fake_rsync(src, dest, cfg, **kwargs):
        def localize(value):
            value = str(value)
            if ":/remote/feishu/bridge" in value:
                suffix = value.split(":/remote/feishu/bridge", 1)[1].lstrip("/")
                return remote_base / suffix
            return __import__("pathlib").Path(value.rstrip("/"))

        left, right = localize(src), localize(dest)
        if not left.exists() and ":/remote/feishu/bridge" in str(src):
            right.mkdir(parents=True, exist_ok=True)
            return
        if left.is_dir():
            right.mkdir(parents=True, exist_ok=True)
            for child in left.glob("*.json"):
                shutil.copy2(child, right / child.name)
        else:
            right.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(left, right)

    def fake_run(argv, *args, **kwargs):
        if "rm" in argv:
            candidate = str(argv[-1])
            suffix = candidate.split("/remote/feishu/bridge/", 1)[1]
            (remote_base / suffix).unlink(missing_ok=True)
        return Result()

    monkeypatch.setattr(hub, "_rsync", fake_rsync)
    monkeypatch.setattr(hub, "_run", fake_run)
    dispatcher = FeishuDispatcher(FakeControl(), store=_StateStore())
    first = sync_client(cfg, dispatcher)
    second = sync_client(cfg, dispatcher)
    assert first == {"ok": True, "mode": "hub", "callbacks": 0, "commands": 1, "errors": 0}
    assert second["commands"] == 0
    response = next((remote_base / "responses" / "tm_laptop").glob("*.json"))
    assert _read_envelope(response)["message_id"] == "om_1"
