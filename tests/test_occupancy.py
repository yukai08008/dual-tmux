from dual_tmux import occupancy, ownership


def test_foreign_holder():
    assert occupancy.foreign_holder({"holder": "tm_other"}, "tm_here") is True
    assert occupancy.foreign_holder({"holder": "tm_here"}, "tm_here") is False
    assert occupancy.foreign_holder({"holder": ""}, "tm_here") is False


def test_resume_claims_occupancy_without_waiting(monkeypatch):
    calls = []

    def claim(name, cfg=None):
        calls.append(name)
        return {"ok": True, "holder": "tm_here", "generation": 13}

    monkeypatch.setattr(occupancy, "claim_occupancy", claim)
    token = ownership.acquire_for_resume(
        {"name": "dt-a"},
        {"safe": True, "action": "claim", "reason": "occupancy_steal"},
    )
    assert token == {"generation": 13, "newly_acquired": True}
    assert calls == ["dt-a"]


def test_unsafe_plan_does_not_claim_occupancy(monkeypatch):
    called = []
    monkeypatch.setattr(occupancy, "claim_occupancy", lambda *_a, **_k: called.append(True))
    try:
        ownership.acquire_for_resume({"name": "dt-a"}, {"safe": False, "reason": "x"})
    except SystemExit as exc:
        assert "preflight rejected" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
    assert called == []


def test_refresh_resume_inputs_pulls_user_and_trigger_persist(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.config import AppConfig

    calls = []
    data = {"name": "dt-a"}
    monkeypatch.setattr(
        "dual_tmux.config.load_config",
        lambda: AppConfig(client="tm_here", server="hub", user="andy"),
    )
    monkeypatch.setattr("dual_tmux.hub.pull", lambda **_k: calls.append(("pull", _k.get("progress"))) or "hub")
    monkeypatch.setattr(
        "dual_tmux.hotfix.sync_persist",
        lambda kind, cfg, **_k: calls.append((kind, cfg.client, _k.get("progress"))),
    )
    monkeypatch.setattr(cli, "load", lambda _path: {**data, "refreshed": True})
    monkeypatch.setattr(cli, "find_dt", lambda _name: "dt-a.json")
    assert cli.refresh_resume_inputs(data)["refreshed"] is True
    assert calls == [
        ("pull", True),
        ("opencode", "tm_here", True),
        ("native", "tm_here", True),
    ]


def test_refresh_resume_inputs_skips_without_hub(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.config import AppConfig

    data = {"name": "dt-a"}
    monkeypatch.setattr(
        "dual_tmux.config.load_config",
        lambda: AppConfig(client="tm_here", server="", user="andy"),
    )
    monkeypatch.setattr(
        "dual_tmux.hub.pull", lambda **_k: (_ for _ in ()).throw(AssertionError("no pull"))
    )
    assert cli.refresh_resume_inputs(data) is data


def test_refresh_resume_inputs_fails_closed_when_persist_sync_fails(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.config import AppConfig

    monkeypatch.setattr(
        "dual_tmux.config.load_config",
        lambda: AppConfig(client="tm_here", server="hub", user="andy"),
    )
    monkeypatch.setattr("dual_tmux.hub.pull", lambda **_k: "hub")
    monkeypatch.setattr(
        "dual_tmux.hotfix.sync_persist",
        lambda kind, cfg, **_k: (_ for _ in ()).throw(SystemExit("persist opencode sync failed"))
        if kind == "opencode"
        else None,
    )
    monkeypatch.setattr(
        cli,
        "load",
        lambda _path: (_ for _ in ()).throw(AssertionError("must not load DST after persist fail")),
    )
    try:
        cli.refresh_resume_inputs({"name": "dt-a"})
    except SystemExit as exc:
        assert "persist opencode sync failed" in str(exc)
    else:
        raise AssertionError("expected SystemExit")



def test_refresh_resume_inputs_prints_sync_stages_before_returning(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.config import AppConfig

    order = []
    monkeypatch.setattr(
        "dual_tmux.config.load_config",
        lambda: AppConfig(client="tm_here", server="hub", user="andy"),
    )
    monkeypatch.setattr(cli.ui, "info", lambda msg: order.append(("info", msg)))
    monkeypatch.setattr(
        "dual_tmux.hub.pull",
        lambda **_k: order.append("pull") or "hub",
    )
    monkeypatch.setattr(
        "dual_tmux.hotfix.sync_persist",
        lambda kind, cfg, **_k: order.append(("sync", kind)),
    )
    monkeypatch.setattr(cli, "load", lambda _path: {"name": "dt-a", "refreshed": True})
    monkeypatch.setattr(cli, "find_dt", lambda _name: "dt-a.json")
    assert cli.refresh_resume_inputs({"name": "dt-a"})["refreshed"] is True
    assert order == [
        ("info", "pulling Hub state"),
        "pull",
        ("info", "syncing OpenCode sessions"),
        ("sync", "opencode"),
        ("info", "syncing native sessions"),
        ("sync", "native"),
        ("info", "session sync complete"),
    ]


def test_release_occupancy_clears_local_holder(monkeypatch):
    from dual_tmux.config import AppConfig

    monkeypatch.setattr(
        occupancy,
        "load_config",
        lambda: AppConfig(client="tm_here", server="", user="andy"),
    )
    value = occupancy.release_occupancy("dt-a")
    assert value["holder"] == ""


def test_occupancy_script_has_no_lease_sidecar():
    assert "lease_ttl" not in occupancy.SCRIPT
    assert "side_value" not in occupancy.SCRIPT
    assert "if action=='release':" in occupancy.SCRIPT


def test_cmd_resume_unfrozen_dst_fast_fails_without_pull(monkeypatch):
    import argparse

    import pytest

    from dual_tmux import cli, hub

    unfrozen_tunnel = {
        "name": "dt-unfrozen",
        "op": "op_unfrozen",
        "run": "run_unfrozen",
        "trigger": {},
        "bullet": {},
    }
    monkeypatch.setattr(cli, "_resolve", lambda _name: unfrozen_tunnel)
    monkeypatch.setattr(
        hub,
        "pull",
        lambda **_k: pytest.fail("must not run hub.pull for unfrozen tunnel"),
    )
    monkeypatch.setattr(
        cli,
        "refresh_resume_inputs",
        lambda _d: pytest.fail("must not refresh inputs for unfrozen tunnel"),
    )

    err_messages = []
    monkeypatch.setattr(cli.ui, "err", lambda msg: err_messages.append(msg))

    with pytest.raises(SystemExit) as exc:
        cli.cmd_resume(argparse.Namespace(name="dt-unfrozen", plan=False, force=False))

    assert exc.value.code == 1
    assert len(err_messages) == 1
    assert "尚未固化为 DST 会话对" in err_messages[0]
