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
