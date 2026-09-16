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
    monkeypatch.setattr(
        "dual_tmux.recovery.reconcile_remote_runtime",
        lambda _d: {"status": "not-applicable", "changed": False, "locations": []},
    )
    monkeypatch.setattr("dual_tmux.recovery.fence_remote_bullet", lambda _d: [])
    monkeypatch.setattr(cli.oc_ops, "start_cmd", lambda _i, _m: "opencode")
    monkeypatch.setattr(cli.tmux_ops, "ensure_agent", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "freeze_sides", lambda *_a, **_k: {"bullet": False})
    monkeypatch.setattr(cli, "save", lambda _p, d: saved_payloads.append(dict(d)))

    with pytest.raises(SystemExit, match="freeze failed for bullet; unproven model not saved"):
        cli._apply_model_legacy("dt-demo", "new/model", ["bullet"])

    assert not saved_payloads


def test_apply_model_repairs_runtime_and_lands_jump_before_starting(monkeypatch, tmp_path):
    import pytest

    from dual_tmux import cli

    tunnel_file = tmp_path / "dt-demo.json"
    data = {
        "name": "dt-demo",
        "op": "op_demo",
        "run": "run_demo",
        "runtime": {
            "server": "root@10.88.0.20",
            "container": "me_andy_browser",
            "directory": "/workspace",
            "cmd": "ssh -t root@10.88.0.20 docker exec -it me_andy_browser bash",
        },
        "bullet": {"tool": "opencode", "model": "old/model"},
    }
    started = []
    repaired = {
        "status": "repaired",
        "changed": True,
        "locations": [{"location": "cp_gateway_24629", "container": "cp_gateway_24629"}],
    }

    monkeypatch.setattr(cli, "_resolve", lambda _name: data)
    monkeypatch.setattr(cli.hub, "require_active", lambda _data: None)
    monkeypatch.setattr(cli.oc_ops, "probe_model", lambda _m: (True, "ok"))
    monkeypatch.setattr(cli, "find_dt", lambda _name: tunnel_file)
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _t: "ssh")
    monkeypatch.setattr(
        "dual_tmux.recovery.reconcile_remote_runtime", lambda _d: repaired
    )
    monkeypatch.setattr(cli, "write_entry", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_ensure_remote_jump", lambda _d: started.append("jump"))
    monkeypatch.setattr("dual_tmux.recovery.fence_remote_bullet", lambda _d: [])
    monkeypatch.setattr(cli.oc_ops, "start_cmd", lambda _i, _m: "opencode --model new")
    monkeypatch.setattr(
        cli.tmux_ops, "ensure_agent", lambda *_a, **_k: started.append("start")
    )
    monkeypatch.setattr(cli, "freeze_sides", lambda *_a, **_k: {"bullet": True})
    monkeypatch.setattr(cli, "save", lambda _p, d: None)
    monkeypatch.setattr(cli, "load", lambda _p: data)
    monkeypatch.setattr(cli.hub, "push_best_effort", lambda **_k: None)

    cli._apply_model_legacy("dt-demo", "new/model", ["bullet"])
    assert started == ["jump", "start"]


def test_apply_model_refuses_hostkey_prompt(monkeypatch, tmp_path):
    import pytest

    from dual_tmux import cli

    data = {
        "name": "dt-demo",
        "op": "op_demo",
        "run": "run_demo",
        "runtime": {"server": "box", "cmd": "ssh -t box"},
        "bullet": {"tool": "opencode", "model": "old/model"},
    }
    monkeypatch.setattr(cli, "_resolve", lambda _name: data)
    monkeypatch.setattr(cli.hub, "require_active", lambda _data: None)
    monkeypatch.setattr(cli.oc_ops, "probe_model", lambda _m: (True, "ok"))
    monkeypatch.setattr(cli, "find_dt", lambda _name: tmp_path / "dt-demo.json")
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _t: "ssh")
    monkeypatch.setattr(
        "dual_tmux.recovery.reconcile_remote_runtime",
        lambda _d: {"status": "healthy", "changed": False, "locations": []},
    )
    monkeypatch.setattr(
        cli,
        "_ensure_remote_jump",
        lambda _d: (_ for _ in ()).throw(SystemExit("[err] run_demo is waiting on an SSH host-key prompt")),
    )
    monkeypatch.setattr(
        cli.tmux_ops,
        "ensure_agent",
        lambda *_a, **_k: pytest.fail("must not start into host-key prompt"),
    )

    with pytest.raises(SystemExit, match="host-key prompt"):
        cli._apply_model_legacy("dt-demo", "new/model", ["bullet"])


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
    monkeypatch.setattr(
        "dual_tmux.recovery.reconcile_remote_runtime",
        lambda _d: {"status": "not-applicable", "changed": False, "locations": []},
    )
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
