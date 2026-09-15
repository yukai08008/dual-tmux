import re
import subprocess
from pathlib import Path

import pytest

from dual_tmux import activity, cli, log, recovery
from dual_tmux.control import ControlService
from dual_tmux.store import save, tunnels_dir

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "dual_tmux"


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))


def _tunnel() -> dict:
    return {
        "name": "dt-msg",
        "op": "op_msg",
        "run": "run_msg",
        "trigger": {"tool": "opencode"},
        "bullet": {"tool": "opencode", "session_id": "ses_b1"},
        "runtime": {
            "server": "box",
            "container": "c1",
            "directory": "/workspace",
            "cmd": "ssh box",
        },
    }


def _events(kind: str = "") -> list[dict]:
    return log.read_events(limit=500, kind=kind)


# --- log v2 model ------------------------------------------------------


def test_emit_writes_sev_and_cat_with_fallback(monkeypatch):
    row = log.emit("dt.custom")
    assert row["sev"] == "info"
    assert row["cat"] == "system"
    row = log.emit("dt.custom", sev="bogus", cat="bogus")
    assert row["sev"] == "info"
    assert row["cat"] == "system"
    row = log.emit("anything", sev="warn", cat="trigger")
    assert row["sev"] == "warn"
    assert row["cat"] == "trigger"


def test_meta_fallback_rules():
    assert log.meta("x.fail")["sev"] == "error"
    assert log.meta("x.reject")["sev"] == "warn"
    assert log.meta("x.stalled")["sev"] == "warn"
    assert log.meta("trigger.custom")["cat"] == "trigger"
    assert log.meta("bullet.custom")["cat"] == "bullet"
    assert log.meta("hub.custom")["cat"] == "system"
    assert log.meta("freeze.bound")["label"] == "DST 绑定提交"


def test_read_events_filters_cat_and_sev_including_legacy_rows():
    from dual_tmux.paths import events_path

    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = '{"ts": "2026-09-15T10:00:00", "kind": "trigger.custom", "pid": 1}'
    modern = log.emit("hub.custom.ok")
    path.write_text(
        legacy + "\n" + path.read_text() + "\n", encoding="utf-8"
    )
    assert modern["sev"] == "info"
    rows = log.read_events(limit=10, cat="trigger")
    assert any(r["kind"] == "trigger.custom" for r in rows)
    assert all(
        r.get("cat") == "trigger" or log.meta(r["kind"])["cat"] == "trigger"
        for r in rows
    )
    errors = log.read_events(limit=10, sev="error")
    assert all(r.get("sev", log.meta(r["kind"])["sev"]) == "error" for r in errors)


def test_events_file_rotates_beyond_size_gate(monkeypatch):
    from dual_tmux.paths import events_path

    monkeypatch.setattr(log, "_ROTATE_BYTES", 1)
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        log.emit("dt.rot", seq=i)
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    assert len(lines) <= log.MAX_EVENT_LINES
    assert len(lines) >= 1


def test_kind_meta_entries_are_valid():
    for kind, (cat, sev, label) in log.KIND_META.items():
        assert cat in log.CATEGORIES, kind
        assert sev in log.SEVERITIES, kind
        assert label, kind


def test_source_emit_literals_resolve_via_meta():
    pattern = re.compile(r"emit\(\s*([f]?)\"([^\"]+)\"")
    seen = set()
    for py in SRC_DIR.glob("*.py"):
        for match in pattern.finditer(py.read_text(encoding="utf-8")):
            if match.group(1) == "f":
                continue
            seen.add(match.group(2))
    assert seen
    for kind in seen:
        info = log.meta(kind)
        assert info["cat"] in log.CATEGORIES, kind
        assert info["sev"] in log.SEVERITIES, kind


# --- system layer emissions -------------------------------------------


def test_cmd_re_emits_transport_reconnect(monkeypatch):
    save(tunnels_dir() / "dt-msg.json", _tunnel())
    reconnected = []
    monkeypatch.setattr(cli.tmux_ops, "reconnect", lambda pane, cmd: reconnected.append((pane, cmd)))
    cli.cmd_re(type("Args", (), {"name": "dt-msg"})())
    assert reconnected
    rows = _events("transport.reconnect")
    assert rows and rows[-1]["transport"] == "ssh"
    assert rows[-1]["name"] == "dt-msg"


def test_reconcile_emits_status_with_severity(monkeypatch):
    data = _tunnel()
    monkeypatch.setattr(
        recovery,
        "_reconcile_remote_runtime",
        lambda _d, runner=None: {"status": "missing", "changed": False, "locations": []},
    )
    recovery.reconcile_remote_runtime(data)
    row = _events("transport.reconcile")[-1]
    assert row["status"] == "missing"
    assert row["sev"] == "warn"
    monkeypatch.setattr(
        recovery,
        "_reconcile_remote_runtime",
        lambda _d, runner=None: {"status": "healthy", "changed": False, "locations": []},
    )
    recovery.reconcile_remote_runtime(data)
    assert _events("transport.reconcile")[-1]["sev"] == "info"


def test_resume_claim_reason_reaches_occupancy_event(monkeypatch):
    import dual_tmux.occupancy as occ
    from dual_tmux import ownership

    monkeypatch.setattr(
        occ,
        "_remote",
        lambda name, action, cfg=None: {
            "ok": True,
            "holder": "tm_here",
            "generation": 4,
        },
    )
    ownership.acquire_for_resume(
        {"name": "dt-msg"}, {"safe": True, "reason": "occupancy_steal"}
    )
    row = _events("hub.occupancy")[-1]
    assert row["reason"] == "occupancy_steal"
    assert row["generation"] == 4


# --- trigger / bullet layer emissions ---------------------------------


def _armed_service(monkeypatch, sent):
    save(tunnels_dir() / "dt-msg.json", _tunnel())
    monkeypatch.setattr("dual_tmux.hub.require_active", lambda _data: {})
    monkeypatch.setattr(
        "dual_tmux.control.tmux_ops.send_keys",
        lambda pane, text: sent.append((pane, text)),
    )
    return ControlService()


def test_service_send_emits_side_events_with_truncated_preview(monkeypatch):
    sent = []
    service = _armed_service(monkeypatch, sent)
    service.send("dt-msg", "hello " * 30, "trigger")
    row = _events("trigger.send")[-1]
    assert row["chars"] == 180
    assert len(row["preview"]) <= 60
    service.send("dt-msg", "do the thing", "bullet")
    assert _events("bullet.send")[-1]["name"] == "dt-msg"


def test_service_interrupt_emits_side_event(monkeypatch):
    interrupted = []
    save(tunnels_dir() / "dt-msg.json", _tunnel())
    monkeypatch.setattr("dual_tmux.hub.require_active", lambda _data: {})
    monkeypatch.setattr(
        "dual_tmux.control.tmux_ops.send_interrupt",
        lambda pane, key: interrupted.append((pane, key)),
    )
    ControlService().interrupt("dt-msg", "bullet", "esc")
    row = _events("bullet.interrupt")[-1]
    assert row["interrupt"] == "Escape"
    assert interrupted


def _start_side_env(monkeypatch, ready):
    data = _tunnel()
    monkeypatch.setattr(cli.oc_ops, "resume_cmd", lambda info: "opencode")
    monkeypatch.setattr(cli.oc_ops, "start_cmd", lambda info, model: "opencode")
    monkeypatch.setattr(cli.opsdir, "prepare", lambda _data: "/tmp/ops")
    monkeypatch.setattr(cli.tmux_ops, "ensure_agent", lambda name, cmd, cwd="": True)
    monkeypatch.setattr(cli.tmux_ops, "pane_command", lambda _name: "opencode")
    monkeypatch.setattr(cli.tmux_ops, "pane_info", lambda _name: {})

    def fake_wait(_pane, _sid, timeout=12):
        if ready is False:
            raise SystemExit("[err] not ready")

    monkeypatch.setattr(cli, "_wait_opencode_ready", fake_wait)
    return data


def test_start_side_emits_start_ok(monkeypatch):
    data = _start_side_env(monkeypatch, ready=True)
    data["trigger"]["session_id"] = "ses_t1"
    cli._start_side(data, data["op"], "trigger", resume=True)
    assert _events("trigger.start.ok")[-1]["pane"] == "op_msg"


def test_start_side_ready_timeout_emits_start_fail(monkeypatch):
    data = _start_side_env(monkeypatch, ready=False)
    data["trigger"]["session_id"] = "ses_t1"
    with pytest.raises(SystemExit):
        cli._start_side(data, data["op"], "trigger", resume=True)
    row = _events("trigger.start.fail")[-1]
    assert row["sev"] == "error"
    assert "not ready" in row["error"]


def test_fence_remote_bullet_emits_killed_pids(monkeypatch):
    monkeypatch.setattr(
        recovery,
        "_remote_command",
        lambda data, script, runner=None, **_kw: subprocess.CompletedProcess(
            [], 0, stdout="DT_KILLED=11 12\n"
        ),
    )
    killed = recovery.fence_remote_bullet(_tunnel(), runner=subprocess.run)
    assert killed == [11, 12]
    row = _events("bullet.fence")[-1]
    assert row["pids"] == [11, 12]
    assert row["session"] == "ses_b1"


def _evidence_env(monkeypatch, phase_by_call=None, text_by_call=None):
    data = _tunnel()
    state = {
        "phase": (phase_by_call or ["working"])[0],
        "text": "answer one",
    }

    def fake_phase(_text, _tool):
        return state["phase"]

    monkeypatch.setattr(activity, "_agent_phase", fake_phase)
    monkeypatch.setattr(activity.tmux_ops, "pane_command", lambda _pane: "opencode")
    monkeypatch.setattr(activity.tmux_ops, "has_session", lambda _pane: True)
    monkeypatch.setattr(activity.tmux_ops, "attached_clients", lambda _pane: 0)

    def run(now, phase=None, text=None):
        if phase is not None:
            state["phase"] = phase
        if text is not None:
            state["text"] = text
        return activity.activity_evidence(
            data, now=now, capture=lambda _pane: state["text"]
        )

    return run


def test_activity_transitions_emit_edge_triggered_events(monkeypatch):
    run = _evidence_env(monkeypatch, [])
    run(100, phase="working", text="answer one")  # first sample: no prior state
    assert not _events("trigger.turn")
    run(200, phase="idle")  # working -> idle: turn.end for both sides
    assert _events("trigger.turn.end") and _events("bullet.run.end")
    run(300, phase="working", text="answer two")  # idle -> working: turn.start
    assert _events("trigger.turn.start") and _events("bullet.run.start")
    before = len(_events())
    run(400, text="answer three")  # working -> working: no transition event
    assert len(_events()) == before


def test_activity_stalled_transition_emits_warn(monkeypatch):
    run = _evidence_env(monkeypatch, [])
    run(100, phase="working", text="answer one")
    run(100 + activity.STALL_SECONDS + 1)  # same fingerprint: stalled
    row = _events("trigger.stalled")[-1]
    assert row["sev"] == "warn"
    assert _events("bullet.stalled")


def test_observe_emits_probe_fail_once_per_episode(monkeypatch):
    def failing(_data):
        return {
            "healthy": False,
            "checked_at": "2026-09-15T10:00:00",
            "failures": ["trigger down", "bullet down"],
            "layers": {
                "trigger_agent": {"ok": False, "status": "down"},
                "bullet_agent": {"ok": False, "status": "down"},
            },
        }

    data = _tunnel()
    data["auto_recover"] = False
    for now in (1, 2, 3, 4):
        recovery.observe(
            data, now=now, prober=failing, recoverer=lambda _d: {"healthy": False}
        )
    assert len(_events("trigger.probe.fail")) == 1
    assert len(_events("bullet.probe.fail")) == 1
    assert _events("bullet.probe.fail")[-1]["sev"] == "warn"


# --- display surfaces ---------------------------------------------------


def test_control_events_enriches_legacy_rows_and_filters():
    from dual_tmux.paths import events_path

    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"ts": "2026-09-15T10:00:00", "kind": "trigger.custom", "pid": 1}\n',
        encoding="utf-8",
    )
    service = ControlService()
    rows = service.events(limit=10, cat="trigger").data
    assert rows and rows[-1]["cat"] == "trigger"
    assert rows[-1]["sev"] == "info"
    assert service.events(limit=10, cat="bullet").data == []


def test_dt_log_parser_accepts_cat_and_sev():
    args = cli.build_parser().parse_args(["log", "--cat", "trigger", "--sev", "warn"])
    assert args.cat == "trigger"
    assert args.sev == "warn"
    args = cli.build_parser().parse_args(["log"])
    assert args.cat == "" and args.sev == ""


def test_web_events_page_renders_filters_and_badges():
    from dual_tmux.web_pages import events_page, tunnels_page

    page = events_page()
    assert "event-cat" in page and "event-sev" in page
    assert "EVENT_LABELS" in page
    assert "sev-error" in page and "cat-bullet" in page
    assert "隧道详情" not in page  # events page is standalone
    tunnels = tunnels_page("")
    assert "eventbox" in tunnels and "loadEventsBox" in tunnels


def test_transport_of_classifies_jump_commands():
    assert cli.tmux_ops.transport_of("ssh box docker attach") == "ssh"
    assert cli.tmux_ops.transport_of("docker exec -it c1 sh") == "docker"
    assert cli.tmux_ops.transport_of("echo hi") == "other"
