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
    monkeypatch.setattr("dual_tmux.hub.pull", lambda: calls.append("pull") or "hub")
    monkeypatch.setattr(
        "dual_tmux.hotfix.sync_persist",
        lambda kind, cfg: calls.append((kind, cfg.client)),
    )
    monkeypatch.setattr(cli, "load", lambda _path: {**data, "refreshed": True})
    monkeypatch.setattr(cli, "find_dt", lambda _name: "dt-a.json")
    assert cli.refresh_resume_inputs(data)["refreshed"] is True
    assert calls == ["pull", ("opencode", "tm_here"), ("native", "tm_here")]


def test_refresh_resume_inputs_skips_without_hub(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.config import AppConfig

    data = {"name": "dt-a"}
    monkeypatch.setattr(
        "dual_tmux.config.load_config",
        lambda: AppConfig(client="tm_here", server="", user="andy"),
    )
    monkeypatch.setattr(
        "dual_tmux.hub.pull", lambda: (_ for _ in ()).throw(AssertionError("no pull"))
    )
    assert cli.refresh_resume_inputs(data) is data


def test_refresh_resume_inputs_fails_closed_when_persist_sync_fails(monkeypatch):
    from dual_tmux import cli
    from dual_tmux.config import AppConfig

    monkeypatch.setattr(
        "dual_tmux.config.load_config",
        lambda: AppConfig(client="tm_here", server="hub", user="andy"),
    )
    monkeypatch.setattr("dual_tmux.hub.pull", lambda: "hub")
    monkeypatch.setattr(
        "dual_tmux.hotfix.sync_persist",
        lambda kind, cfg: (_ for _ in ()).throw(SystemExit("persist opencode sync failed"))
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
