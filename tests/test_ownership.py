import pytest

from dual_tmux import ownership


def _data():
    return {
        "name": "dt-a",
        "op": "op_a",
        "run": "run_a",
        "runtime": {"server": ""},
        "trigger": {"tool": "opencode", "session_id": "ses_trigger"},
        "bullet": {"tool": "opencode", "session_id": "ses_bullet"},
    }


def test_snapshot_schema_and_duplicate_writer_fail_closed(monkeypatch):
    monkeypatch.setattr(
        ownership.hub,
        "read_ownership",
        lambda _name: {
            "state": "owned",
            "holder": "tm_a",
            "generation": 4,
            "source": "v2",
            "evidence": {},
            "conflict": False,
        },
    )
    monkeypatch.setattr(ownership, "read_evidence", lambda _name: {})
    monkeypatch.setattr(ownership.tmux_ops, "has_session", lambda _pane: True)
    monkeypatch.setattr(ownership.tmux_ops, "pane_command", lambda _pane: "opencode")
    monkeypatch.setattr(ownership.tmux_ops, "attached_clients", lambda _pane: 0)
    monkeypatch.setattr(
        ownership,
        "probe_writers",
        lambda _data, role: {
            "status": "duplicate" if role == "bullet" else "ok",
            "count": 2 if role == "bullet" else 1,
            "pids": [1, 2],
            "reason": "duplicate_writer" if role == "bullet" else "",
        },
    )
    result = ownership.snapshot(_data())
    assert set(result) == {
        "schema",
        "name",
        "lease",
        "runtime",
        "attached",
        "progress",
        "writers",
        "snapshot",
        "native_snapshots",
        "takeover",
    }
    assert result["takeover"] == {
        "safe": False,
        "action": "stop",
        "reason": "bullet_duplicate_writer",
    }


def test_foreign_idle_detached_can_request_handoff(monkeypatch):
    evidence = {
        "sampled_at": 100,
        "sides": {
            role: {
                "runtime": "agent",
                "attached": False,
                "state": "idle",
                "writers": {"status": "ok", "count": 1, "pids": [1], "reason": ""},
            }
            for role in ("trigger", "bullet")
        },
    }
    monkeypatch.setattr(
        ownership.hub,
        "read_ownership",
        lambda _name: {
            "state": "foreign",
            "holder": "tm_other",
            "generation": 8,
            "source": "v2",
            "evidence": evidence,
            "conflict": False,
        },
    )
    monkeypatch.setattr(ownership.time, "time", lambda: 120)
    result = ownership.plan_resume(_data())
    assert result["safe"] is True
    assert result["action"] == "request_handoff"


def test_foreign_idle_attached_can_request_explicit_handoff(monkeypatch):
    evidence = {
        "sampled_at": 100,
        "sides": {
            role: {
                "runtime": "agent",
                "attached": True,
                "state": "idle",
                "writers": {"status": "ok", "count": 1, "pids": [1], "reason": ""},
            }
            for role in ("trigger", "bullet")
        },
    }
    monkeypatch.setattr(
        ownership.hub,
        "read_ownership",
        lambda _name: {
            "state": "foreign",
            "holder": "tm_other",
            "generation": 8,
            "source": "v2",
            "evidence": evidence,
            "conflict": False,
        },
    )
    monkeypatch.setattr(ownership.time, "time", lambda: 120)
    result = ownership.plan_resume(_data())
    assert result["safe"] is True
    assert result["action"] == "request_handoff"


def test_foreign_unknown_attachment_still_fails_closed(monkeypatch):
    evidence = {
        "sampled_at": 100,
        "sides": {
            role: {
                "runtime": "agent",
                "attached": None if role == "trigger" else False,
                "state": "idle",
                "writers": {"status": "ok", "count": 1, "pids": [1], "reason": ""},
            }
            for role in ("trigger", "bullet")
        },
    }
    monkeypatch.setattr(
        ownership.hub,
        "read_ownership",
        lambda _name: {
            "state": "foreign",
            "holder": "tm_other",
            "generation": 8,
            "source": "v2",
            "evidence": evidence,
            "conflict": False,
        },
    )
    monkeypatch.setattr(ownership.time, "time", lambda: 120)
    result = ownership.plan_resume(_data())
    assert result["safe"] is False
    assert result["reason"] == "trigger_attachment_unknown"


def test_probe_failure_is_unknown_not_zero(monkeypatch):
    monkeypatch.setattr(
        ownership.subprocess,
        "run",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("no ps")),
    )
    assert ownership.probe_writers(_data(), "trigger") == {
        "status": "unknown",
        "count": None,
        "pids": [],
        "reason": "probe_failed",
    }


def test_unsafe_plan_never_claims(monkeypatch):
    called = []
    monkeypatch.setattr(ownership.hub, "claim", lambda *_a, **_kw: called.append(True))
    with pytest.raises(SystemExit, match="preflight rejected"):
        ownership.acquire_for_resume(_data(), {"safe": False, "reason": "probe_failed"})
    assert called == []


def test_stale_foreign_evidence_is_never_takeover_safe(monkeypatch):
    evidence = {
        "sampled_at": 100,
        "sides": {
            role: {
                "runtime": "agent",
                "attached": False,
                "state": "idle",
                "writers": {"status": "ok", "count": 1, "pids": [1], "reason": ""},
            }
            for role in ("trigger", "bullet")
        },
    }
    monkeypatch.setattr(
        ownership.hub,
        "read_ownership",
        lambda _name: {
            "state": "foreign",
            "holder": "tm_other",
            "generation": 8,
            "source": "v2",
            "evidence": evidence,
            "conflict": False,
        },
    )
    monkeypatch.setattr(ownership.time, "time", lambda: 1000)
    result = ownership.snapshot(_data())
    assert result["takeover"] == {
        "safe": False,
        "action": "stop",
        "reason": "owner_evidence_stale",
    }


def test_native_client_store_allows_protocol_handoff(monkeypatch):
    data = _data()
    data["trigger"] = {
        "tool": "codex",
        "session_id": "00000000-0000-0000-0000-000000000001",
    }
    evidence = {
        "sampled_at": 100,
        "sides": {
            role: {
                "runtime": "agent",
                "attached": False,
                "state": "idle",
                "writers": {"status": "ok", "count": 1, "pids": [1], "reason": ""},
            }
            for role in ("trigger", "bullet")
        },
    }
    monkeypatch.setattr(
        ownership.hub,
        "read_ownership",
        lambda _name: {
            "state": "foreign",
            "holder": "tm_other",
            "generation": 8,
            "source": "v2",
            "evidence": evidence,
            "conflict": False,
        },
    )
    monkeypatch.setattr(ownership.time, "time", lambda: 120)
    assert ownership.snapshot(data)["takeover"] == {
        "safe": True,
        "action": "request_handoff",
        "reason": "foreign_idle_detached",
    }
    assert ownership.snapshot(data)["native_snapshots"]["trigger"]["tool"] == "codex"


def test_native_snapshot_conflict_blocks_takeover(monkeypatch):
    data = _data()
    data["trigger"] = {
        "tool": "claude",
        "session_id": "00000000-0000-0000-0000-000000000001",
    }
    evidence = {
        "sampled_at": 100,
        "sides": {
            role: {
                "runtime": "agent",
                "attached": False,
                "state": "idle",
                "writers": {"status": "ok", "count": 1, "pids": [1], "reason": ""},
            }
            for role in ("trigger", "bullet")
        },
    }
    monkeypatch.setattr(
        ownership.hub,
        "read_ownership",
        lambda _name: {
            "state": "foreign",
            "holder": "tm_other",
            "generation": 8,
            "source": "v2",
            "evidence": evidence,
            "conflict": False,
        },
    )
    monkeypatch.setattr(ownership.time, "time", lambda: 120)
    monkeypatch.setattr(
        "dual_tmux.native_persist.inspect_session",
        lambda info: {
            "status": "conflict" if info.get("tool") == "claude" else "unsupported"
        },
    )
    assert ownership.snapshot(data)["takeover"] == {
        "safe": False,
        "action": "stop",
        "reason": "trigger_native_snapshot_conflict",
    }


@pytest.mark.parametrize("tool", ["opencode", "codex", "claude"])
def test_local_writer_probe_supports_all_clients(monkeypatch, tool):
    data = _data()
    data["trigger"] = {"tool": tool, "session_id": "session-123"}
    monkeypatch.setattr(ownership, "_local_session_pids", lambda _sid: [42])
    assert ownership.probe_writers(data, "trigger") == {
        "status": "ok",
        "count": 1,
        "pids": [42],
        "reason": "",
    }


def test_remote_writer_probe_supports_container_runtime(monkeypatch):
    from dual_tmux import recovery

    data = _data()
    data["runtime"] = {"server": "tom7r", "container": "box"}
    data["bullet"] = {"tool": "claude", "session_id": "session-123"}
    monkeypatch.setattr(recovery, "remote_session_pids", lambda _data: [7])
    assert ownership.probe_writers(data, "bullet")["pids"] == [7]


def test_local_blank_opencode_argv_uses_exact_live_pane_session(monkeypatch):
    from dual_tmux import oc

    data = _data()
    monkeypatch.setattr(ownership, "_local_session_pids", lambda _sid: [])
    monkeypatch.setattr(
        ownership.tmux_ops,
        "pane_info",
        lambda _pane: {"pid": "42", "cmd": "opencode", "cwd": "/workspace"},
    )
    monkeypatch.setattr(
        oc,
        "from_pane",
        lambda *_args, **_kwargs: oc.OcSession("ses_trigger", "live"),
    )
    assert ownership.probe_writers(data, "trigger")["pids"] == [42]


def test_remote_blank_opencode_argv_uses_exact_live_session(monkeypatch):
    from dual_tmux import oc, recovery

    data = _data()
    data["runtime"] = {"server": "box"}
    monkeypatch.setattr(recovery, "remote_session_pids", lambda _data: [])
    monkeypatch.setattr(
        ownership.tmux_ops,
        "pane_info",
        lambda _pane: {"pid": "84", "cmd": "ssh", "cwd": "/workspace"},
    )
    monkeypatch.setattr("dual_tmux.cli._ssh_argv", lambda _data: ["ssh", "box"])
    monkeypatch.setattr(
        oc,
        "active_remote",
        lambda *_args, **_kwargs: oc.OcSession("ses_bullet", "live"),
    )
    assert ownership.probe_writers(data, "bullet")["pids"] == [84]


def test_blank_opencode_argv_rejects_different_live_session(monkeypatch):
    from dual_tmux import oc

    data = _data()
    monkeypatch.setattr(ownership, "_local_session_pids", lambda _sid: [])
    monkeypatch.setattr(
        ownership.tmux_ops,
        "pane_info",
        lambda _pane: {"pid": "42", "cmd": "opencode", "cwd": "/workspace"},
    )
    monkeypatch.setattr(
        oc,
        "from_pane",
        lambda *_args, **_kwargs: oc.OcSession("ses_other", "other"),
    )
    assert ownership.probe_writers(data, "trigger")["count"] == 0


def test_resume_plan_cli_skips_ready_checks_and_audit_writes(monkeypatch):
    from dual_tmux import cli

    seen = []
    monkeypatch.setattr(cli.sys, "argv", ["dt", "resume", "dt-a", "--plan"])
    monkeypatch.setattr(
        cli,
        "ensure_ready",
        lambda: pytest.fail("plan must not run readiness mutations"),
    )
    monkeypatch.setattr(
        cli.ev,
        "emit",
        lambda *_a, **_kw: pytest.fail("plan must not write audit events"),
    )
    monkeypatch.setattr(
        cli, "cmd_resume", lambda args: seen.append((args.name, args.plan))
    )
    cli.main()
    assert seen == [("dt-a", True)]


def test_ownership_cache_is_atomic_read_only_and_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    facts = {
        "schema": 1,
        "name": "dt-a",
        "takeover": {"safe": True, "action": "resume", "reason": "already_owned"},
    }
    path = ownership.write_cache(facts, now=100)
    assert path == tmp_path / "ownership-cache" / "dt-a.json"
    fresh = ownership.read_cache("dt-a", now=120)
    assert fresh == {
        "available": True,
        "cached_at": 100,
        "age_seconds": 20,
        "freshness": "fresh",
        "facts": facts,
    }
    assert ownership.read_cache("dt-a", now=400)["freshness"] == "stale"
    assert ownership.read_cache("missing", now=120)["freshness"] == "missing"


def test_plan_from_cached_facts_preserves_frozen_shape():
    facts = {
        "schema": 1,
        "name": "dt-a",
        "takeover": {
            "safe": True,
            "action": "request_handoff",
            "reason": "foreign_idle_detached",
        },
    }
    plan = ownership.plan_from_facts(_data(), facts)
    assert plan["steps"] == ["request_handoff", "prepare", "restore", "verify"]
    assert plan["ownership"] is facts
