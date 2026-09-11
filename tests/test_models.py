from dual_tmux.oc import list_models, probe_model


def test_list_models_parses_lines(monkeypatch):
    class R:
        returncode = 0
        stdout = "xs-grok/grok-4.6\ncli-proxy/kimi-k3\nnot-a-model\n"
        stderr = ""

    monkeypatch.setattr("dual_tmux.oc.have_opencode", lambda: True)
    monkeypatch.setattr("dual_tmux.oc.subprocess.run", lambda *a, **k: R())
    assert list_models() == ["xs-grok/grok-4.6", "cli-proxy/kimi-k3"]


def test_probe_model_ok(monkeypatch):
    class R:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("dual_tmux.oc.have_opencode", lambda: True)
    monkeypatch.setattr("dual_tmux.oc.subprocess.run", lambda *a, **k: R())
    ok, detail = probe_model("xs-grok/grok-4.6")
    assert ok
    assert "ok" in detail


def test_probe_model_fail(monkeypatch):
    class R:
        returncode = 1
        stdout = ""
        stderr = "unknown model"

    monkeypatch.setattr("dual_tmux.oc.have_opencode", lambda: True)
    monkeypatch.setattr("dual_tmux.oc.subprocess.run", lambda *a, **k: R())
    ok, detail = probe_model("nope/x")
    assert not ok
    assert "unknown" in detail


def test_apply_model_fail_closed_when_freeze_fails(monkeypatch, tmp_path):
    import pytest

    from dual_tmux import cli

    tunnel_file = tmp_path / "dt-demo.json"
    data = {
        "name": "dt-demo",
        "op": "op_demo",
        "run": "run_demo",
        "bullet": {"tool": "opencode", "model": "old/model"},
    }
    saved_payloads = []

    monkeypatch.setattr(cli, "_resolve", lambda _name: dict(data))
    monkeypatch.setattr(cli.hub, "require_active", lambda _data: None)
    monkeypatch.setattr(cli.oc_ops, "probe_model", lambda _m: (True, "ok"))
    monkeypatch.setattr(cli, "find_dt", lambda _name: tunnel_file)
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _t: "")
    monkeypatch.setattr("dual_tmux.recovery.fence_remote_bullet", lambda _d: [])
    monkeypatch.setattr(cli.oc_ops, "start_cmd", lambda _i, _m: "opencode")
    monkeypatch.setattr(cli.tmux_ops, "ensure_agent", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "freeze_sides", lambda *_a, **_k: {"bullet": False})
    monkeypatch.setattr(cli, "save", lambda _p, d: saved_payloads.append(dict(d)))

    with pytest.raises(SystemExit, match="freeze failed for bullet; unproven model not saved"):
        cli._apply_model_legacy("dt-demo", "new/model", ["bullet"])

    assert not saved_payloads


def test_apply_model_saves_when_freeze_succeeds(monkeypatch, tmp_path):
    from dual_tmux import cli

    tunnel_file = tmp_path / "dt-demo.json"
    data = {
        "name": "dt-demo",
        "op": "op_demo",
        "run": "run_demo",
        "bullet": {"tool": "opencode", "model": "old/model"},
    }
    saved_payloads = []

    monkeypatch.setattr(cli, "_resolve", lambda _name: dict(data))
    monkeypatch.setattr(cli.hub, "require_active", lambda _data: None)
    monkeypatch.setattr(cli.oc_ops, "probe_model", lambda _m: (True, "ok"))
    monkeypatch.setattr(cli, "find_dt", lambda _name: tunnel_file)
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _t: "")
    monkeypatch.setattr("dual_tmux.recovery.fence_remote_bullet", lambda _d: [])
    monkeypatch.setattr(cli.oc_ops, "start_cmd", lambda _i, _m: "opencode")
    monkeypatch.setattr(cli.tmux_ops, "ensure_agent", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "freeze_sides", lambda *_a, **_k: {"bullet": True})
    monkeypatch.setattr(cli, "save", lambda _p, d: saved_payloads.append(dict(d)))
    monkeypatch.setattr(cli, "load", lambda _p: saved_payloads[-1])
    monkeypatch.setattr(cli.hub, "push_best_effort", lambda **_k: None)

    res = cli._apply_model_legacy("dt-demo", "new/model", ["bullet"])
    assert len(saved_payloads) == 1
    assert res["bullet"]["model"] == "new/model"
    assert res["times"]["freeze_at"]
