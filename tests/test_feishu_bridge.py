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
    format_feishu_reply,
    hub_feishu_status,
    publish_installation_to_hub,
    sync_client,
    sync_installation_from_hub,
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


def test_bridge_store_keeps_event_receipt_after_command_consumption(dt_home, tmp_path):
    store = BridgeStore(tmp_path / "spool")
    command, accepted = store.enqueue_once(
        "tm_laptop", "commands", "evt-1", {"text": "/dt ls"}
    )
    _same, replay_accepted = store.enqueue_once(
        "tm_laptop", "commands", "evt-1", {"text": "/dt show changed"}
    )
    assert accepted is True
    assert replay_accepted is False
    assert _read_envelope(command)["text"] == "/dt ls"
    command.unlink()
    _gone, consumed_replay = store.enqueue_once(
        "tm_laptop", "commands", "evt-1", {"text": "/dt show changed"}
    )
    receipt = next((store.root / "receipts" / "commands" / "tm_laptop").glob("*.json"))
    assert consumed_replay is False
    assert not command.exists()
    assert _read_envelope(receipt)["text"] == "/dt ls"
    for directory in (
        store.root,
        store.root / "commands",
        store.root / "commands" / "tm_laptop",
        store.root / "receipts",
        store.root / "receipts" / "commands",
        store.root / "receipts" / "commands" / "tm_laptop",
    ):
        assert directory.stat().st_mode & 0o777 == 0o700


def test_bridge_store_reports_unreadable_route_without_leaking_path(
    dt_home, monkeypatch, tmp_path
):
    store = BridgeStore(tmp_path / "spool")
    identity = OperatorIdentity(open_id="ou_a")
    route = store.root / "routes" / "ignored.json"

    def denied(self):
        if self.parent.name == "routes":
            raise PermissionError("/private/hub/user/feishu/bridge/routes")
        return False

    monkeypatch.setattr(type(route), "is_file", denied)
    with pytest.raises(FeishuError) as caught:
        store.client_for(identity)
    assert caught.value.code == "bridge_unavailable"
    assert "/private/" not in str(caught.value)


def test_distinct_user_namespaces_do_not_share_operator_routes(dt_home, tmp_path):
    identity = OperatorIdentity(open_id="ou_same_enterprise_user")
    user_a = BridgeStore(tmp_path / "user_a" / "dual-tmux" / "feishu" / "bridge")
    user_b = BridgeStore(tmp_path / "user_b" / "dual-tmux" / "feishu" / "bridge")
    user_a.register_routes(identity, "tm_a")
    user_b.register_routes(identity, "tm_b")
    assert user_a.client_for(identity) == "tm_a"
    assert user_b.client_for(identity) == "tm_b"
    assert set(user_a.root.rglob("*.json")).isdisjoint(user_b.root.rglob("*.json"))


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
            "chat_id": "oc_1",
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
    envelope = _read_envelope(response)
    assert envelope["message_id"] == "om_1"
    assert envelope["chat_id"] == "oc_1"
    assert envelope["reply"]["msg_type"] == "interactive"
    assert "**隧道列表（1）**" in envelope["reply"]["content"]["elements"][0]["text"]["content"]
    assert '"operation"' not in envelope["reply"]["fallback"]


def test_feishu_list_reply_is_human_markdown_not_raw_json():
    reply = format_feishu_reply(
        {
            "ok": True,
            "result": {
                "ok": True,
                "operation": "tunnel.list",
                "data": [
                    {
                        "name": "dt-demo",
                        "client": "tm_laptop",
                        "trigger": {"tool": "codex", "model": "gpt-5"},
                        "bullet": {"tool": "claude", "model": "sonnet"},
                    }
                ],
                "warnings": [],
            },
        }
    )
    assert reply["msg_type"] == "interactive"
    markdown = reply["content"]["elements"][0]["text"]["content"]
    assert "dt-demo" in markdown
    assert "Trigger：codex · gpt-5" in markdown
    assert "Bullet：claude · sonnet" in markdown
    assert not markdown.lstrip().startswith("{")


def test_publish_installation_sends_only_encrypted_bundle_and_hashed_route(
    dt_home, monkeypatch, tmp_path
):
    from dual_tmux import hub
    from dual_tmux.feishu import CredentialVault

    vault = CredentialVault()
    vault.save("cli_auto", "TOP-SECRET", {"open_id": "ou_secret"})
    copied = []
    commands = []
    timeline = []

    class Result:
        returncode = 0
        stderr = stdout = ""

    def run(argv, *args, **kwargs):
        commands.append(argv)
        timeline.append(("run", argv[-1]))
        return Result()

    monkeypatch.setattr(hub, "_run", run)
    monkeypatch.setattr(hub, "remote_root", lambda cfg: "/remote")
    def capture(src, dest, cfg, **kwargs):
        source = __import__("pathlib").Path(str(src).rstrip("/"))
        content = ""
        if source.is_dir():
            content = "".join(path.read_text() for path in source.glob("*.json"))
        elif source.is_file():
            content = source.read_text(errors="replace")
        copied.append((str(src), str(dest), content))
        timeline.append(("copy", str(dest)))

    monkeypatch.setattr(hub, "_rsync", capture)
    cfg = AppConfig(client="tm_laptop", server="tom7r", user="andy")
    publish_installation_to_hub(cfg, OperatorIdentity(open_id="ou_secret"))
    assert any(dest.endswith("/credential.key") for _, dest, _ in copied)
    assert any(dest.endswith("/installation.json") for _, dest, _ in copied)
    permission_command = next(
        argv[-1] for argv in commands if "owner=$(id -u):$(id -g)" in argv[-1]
    )
    assert "chmod 600" in permission_command
    assert "/remote/feishu/bridge/routes" in permission_command
    assert "find /remote/feishu/bridge -type f -exec chown" in permission_command
    route_copy = next(
        i
        for i, item in enumerate(timeline)
        if item[0] == "copy" and item[1].endswith("/bridge/routes/")
    )
    permission_call = next(
        i
        for i, item in enumerate(timeline)
        if item[0] == "run" and "owner=$(id -u):$(id -g)" in item[1]
    )
    assert permission_call > route_copy
    route_text = next(content for _, dest, content in copied if dest.endswith("/bridge/routes/"))
    assert "ou_secret" not in route_text
    assert "TOP-SECRET" not in vault.installation_path.read_text()


def test_hub_status_reads_only_public_daemon_state(dt_home, monkeypatch):
    from dual_tmux import hub

    calls = []

    class Result:
        def __init__(self, returncode=0, stdout=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def run(argv, *args, **kwargs):
        calls.append(argv)
        if argv[-2:] == ["test", "-f"]:
            return Result()
        if "installation.json" in argv[-1]:
            return Result()
        return Result(
            stdout=json.dumps(
                {
                    "running": True,
                    "connector": "connected",
                    "owner": "hub-instance",
                    "generation": 4,
                }
            )
        )

    monkeypatch.setattr(hub, "_run", run)
    monkeypatch.setattr(hub, "remote_root", lambda cfg: "/remote")
    result = hub_feishu_status(
        AppConfig(client="tm_laptop", server="tom7r", user="andy")
    )
    assert result["installed"] is True
    assert result["daemon"]["generation"] == 4
    assert not any("credential.key" in " ".join(argv) for argv in calls)


def test_failover_sync_validates_then_atomically_installs_shared_bot(
    dt_home, monkeypatch, tmp_path
):
    from dual_tmux import hub
    from dual_tmux.feishu import CredentialVault

    remote = CredentialVault(tmp_path / "remote")
    remote.save("cli_shared", "SHARED-SECRET", {"open_id": "ou_a"})

    def copy(src, dest, cfg, **kwargs):
        name = str(src).rsplit("/", 1)[-1]
        target = __import__("pathlib").Path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(remote.root / name, target)

    monkeypatch.setattr(hub, "_rsync", copy)
    monkeypatch.setattr(hub, "remote_root", lambda cfg: "/remote")
    cfg = AppConfig(client="tm_backup", server="tom7r", user="andy")
    assert sync_installation_from_hub(cfg) is True
    local = CredentialVault().load()
    assert local["app_id"] == "cli_shared"
    assert local["app_secret"] == "SHARED-SECRET"
    assert oct(CredentialVault().key_path.stat().st_mode & 0o777) == "0o600"
