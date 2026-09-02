from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, activity, hub, opsdir, skillmgr, statusbar, ui
from . import cron as cron_ops
from . import hotfix as hotfix_ops
from . import log as ev
from . import memory as mem_ops
from . import oc as oc_ops
from . import tmux as tmux_ops
from . import workpoint as wp
from .config import (
    AppConfig,
    init_config,
    load_config,
    make_config,
    switch_config,
    write_config,
)
from .health import collect_checks, ensure_ready, guide_if_needed, print_checks
from .identity import SOURCE_HINT, USER_HINT, remote_dt_root, remote_sessions_root
from .paths import config_path, home_dir, tunnels_dir
from .runtime import build_cmd
from .sshutil import list_ssh_hosts, parse_ssh_target
from .store import (
    default_names,
    find_dt,
    iter_dt_files,
    latest_dt,
    legal_op,
    legal_run,
    load,
    now_iso,
    occupied,
    remove_dt,
    save,
    write_entry,
)


def require_config() -> AppConfig:
    return load_config()


def cmd_version(_: argparse.Namespace) -> None:
    if sys.stdout.isatty():
        ui.print_version(
            __version__,
            sys.version.split()[0],
            f"{platform.system()} {platform.release()} ({platform.machine()})",
            str(home_dir()),
        )
    else:
        print(f"dt {__version__}")


def cmd_ls(_: argparse.Namespace) -> None:
    from .control import get_control_service

    ui.print_ls(get_control_service().list_tunnels().data)


def cmd_show(args: argparse.Namespace) -> None:
    from .control import ControlError, get_control_service

    try:
        data = get_control_service().get_tunnel(args.name).data
    except ControlError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(data, ensure_ascii=False, indent=2))


def print_inspect(data: dict) -> None:
    ui.print_inspect(data)


def cmd_inspect(args: argparse.Namespace) -> None:
    print_inspect(_resolve(args.name))


def cmd_new(args: argparse.Namespace) -> None:
    cfg = require_config()
    name, default_op, default_run = default_names(args.name)
    op = args.op or default_op
    run = args.run or default_run
    if not legal_op(op):
        raise SystemExit("[err] --op must start with op_")
    if not legal_run(run):
        raise SystemExit("[err] --run must start with run_")
    other = occupied("op", op, skip=name)
    if other:
        raise SystemExit(f"[err] {op} already used by {other}")
    other = occupied("run", run, skip=name)
    if other:
        raise SystemExit(f"[err] {run} already used by {other}")
    if getattr(args, "local", False):
        server = ""
        ssh_port = 22
    elif args.server:
        target = parse_ssh_target(args.server)
        server = target.dest
        ssh_port = target.port
    else:
        server = cfg.server
        ssh_port = cfg.ssh_port
    directory = args.dir or cfg.workspace
    if not server and args.container:
        raise SystemExit(
            "[err] --container currently requires --server; omit it for local mode"
        )
    if not server and not Path(directory).expanduser().is_dir():
        raise SystemExit(f"[err] local directory does not exist: {directory}")
    cmd = args.cmd or build_cmd(server, args.container or "", directory, ssh_port)
    tmux_ops.ensure_session(
        run, cwd=str(Path(directory).expanduser()) if not server else ""
    )
    write_entry(run, cmd)
    data = {
        "name": name,
        "op": op,
        "run": run,
        "client": cfg.client,
        "user": cfg.user,
        "runtime": {
            "server": server,
            "ssh_port": ssh_port,
            "container": args.container or "",
            "directory": directory,
            "cmd": cmd,
        },
        "trigger": oc_ops.empty_side(),
        "bullet": oc_ops.empty_side(),
        "op_point": wp.empty_point(),
        "run_point": wp.empty_point(),
        "times": wp.empty_times(),
        "updated_at": now_iso(),
    }
    data["times"]["created_at"] = data["updated_at"]
    data["op_point"] = wp.discover(op)
    data["run_point"] = wp.discover(run)
    path = tunnels_dir() / f"{name}.json"
    if path.exists():
        old = load(path)
        data["trigger"] = old.get("trigger") or data["trigger"]
        data["bullet"] = old.get("bullet") or data["bullet"]
    save(path, data)
    launch = opsdir.prepare(data)
    tmux_ops.ensure_session(op, cwd=str(launch))
    ev.emit("dt.new", name=name, op=op, run=run, server=server)
    ui.ok(f"registered {name}")
    print_inspect(data)
    ui.print_next_new(name)
    hub.push_best_effort(wait=True)


def cmd_branch(args: argparse.Namespace) -> None:
    src = _resolve(args.src)
    name, op, run = default_names(args.dest)
    if (
        occupied("op", op)
        or occupied("run", run)
        or (tunnels_dir() / f"{name}.json").exists()
    ):
        raise SystemExit(f"[err] {name} already exists")
    cfg = require_config()
    runtime = dict(src.get("runtime") or {})
    run_point = dict(src.get("run_point") or wp.empty_point())
    data = {
        "name": name,
        "op": op,
        "run": run,
        "client": cfg.client,
        "user": cfg.user,
        "branched_from": src.get("name"),
        "runtime": runtime,
        "trigger": oc_ops.empty_side(
            (src.get("trigger") or {}).get("tool") or "opencode"
        ),
        "bullet": oc_ops.empty_side(
            (src.get("bullet") or {}).get("tool") or "opencode"
        ),
        "op_point": dict(src.get("op_point") or wp.empty_point()),
        "run_point": run_point,
        "times": wp.empty_times(),
        "updated_at": now_iso(),
    }
    data["trigger"]["model"] = (src.get("trigger") or {}).get("model") or ""
    data["bullet"]["model"] = (src.get("bullet") or {}).get("model") or ""
    data["times"]["created_at"] = data["updated_at"]
    wp.apply_runtime(data, run_point)
    cmd = (data.get("runtime") or {}).get("cmd") or runtime.get("cmd") or ""
    hops = run_point.get("hops") or []
    if cmd:
        write_entry(run, cmd)
    save(tunnels_dir() / f"{name}.json", data)
    launch = opsdir.prepare(data)
    tmux_ops.ensure_session(op, cwd=str(launch))
    tmux_ops.ensure_session(run)
    if cmd:
        tmux_ops.reconnect(run, cmd)
    elif hops:
        tmux_ops.replay_hops(run, hops)
    landed = tmux_ops.wait_command(run, {"ssh", "docker", "bash", "sh"}, timeout=25)
    if not runtime.get("server"):
        ui.ok(f"{run} local workspace ready")
    elif landed in {"zsh", "", "tmux"}:
        ui.warn(f"{run} jump not landed (cmd={landed or '—'}); still starting oc")
    else:
        ui.ok(f"{run} jump cmd={landed}")
    hub.require_active(data)
    _start_side(data, op, "trigger", data["trigger"].get("model") or "", False)
    time.sleep(0.8)
    _start_side(data, run, "bullet", data["bullet"].get("model") or "", False)
    ui.info("waiting for both opencode sessions")
    freeze_sides(data, ["trigger", "bullet"], "opencode", wait=True)
    wp.stamp(data, "freeze_at")
    save(find_dt(name), data)
    ev.emit(
        "dt.branch",
        src=src.get("name"),
        name=name,
        op=op,
        run=run,
        is_dst=oc_ops.is_dst(data),
    )
    ui.ok(
        f"branched {src.get('name')} → {name}  IS_DST={'yes' if oc_ops.is_dst(data) else 'no'}"
    )
    print_inspect(data)
    hub.push_best_effort(wait=True)


def _side(data: dict, name: str) -> dict:
    from .agentclient import empty as empty_agent_client

    side = data.setdefault(name, oc_ops.empty_side())
    side.setdefault("tool", "opencode")
    side.setdefault("parser", "")
    side.setdefault("model", "")
    side.setdefault("session_id", "")
    side.setdefault("slug", "")
    side.setdefault("agent", "")
    side.setdefault("agent_client", empty_agent_client())
    if not side.get("parser"):
        from .paneparse import parser_id_for_side

        side["parser"] = parser_id_for_side(side)
    return side


def _bind_oc(data: dict, side: str, session: oc_ops.OcSession, tool: str = "") -> None:
    data[side] = oc_ops.as_bind(session, tool)
    data["updated_at"] = now_iso()


def _print_side(label: str, info: dict) -> None:
    client = info.get("agent_client") or {}
    client_text = client.get("name") or "—"
    if client.get("version"):
        client_text += f"@{client['version']}"
    ui.info(
        f"{label}  tool={info.get('tool') or '—'}  "
        f"client={client_text}  "
        f"model={info.get('model') or '—'}  "
        f"session={info.get('session_id') or '—'}"
    )


def cmd_bind(args: argparse.Namespace) -> None:
    require_config()
    path = find_dt(args.name)
    data = load(path)
    trigger = _side(data, "trigger")
    bullet = _side(data, "bullet")
    if args.trigger_tool:
        trigger["tool"] = args.trigger_tool
    if args.trigger_model:
        trigger["model"] = args.trigger_model
    if args.trigger:
        trigger["slug"] = args.trigger
    if args.trigger_id:
        trigger["session_id"] = args.trigger_id
    if args.bullet_tool:
        bullet["tool"] = args.bullet_tool
    if args.bullet_model:
        bullet["model"] = args.bullet_model
    if args.bullet:
        bullet["slug"] = args.bullet
    if args.bullet_id:
        bullet["session_id"] = args.bullet_id
    data["updated_at"] = now_iso()
    save(path, data)
    ui.ok(f"dst {data['name']}")
    _print_side("trigger", trigger)
    _print_side("bullet", bullet)
    hub.push_best_effort(wait=True)


def _resolve(name: str | None) -> dict:
    try:
        path = find_dt(name) if name else latest_dt()
        return load(path)
    except SystemExit:
        if not name:
            raise
        if not hub.enabled():
            raise
        ui.info("tunnel missing locally; pulling hub")
        hub.pull()
        path = find_dt(name)
        return load(path)


def print_next_after_init() -> None:
    ui.print_next_init()


def _start_side(
    data: dict, tmux_name: str, side: str, model: str = "", resume: bool = False
) -> None:
    info = _side(data, side)
    if model:
        info["model"] = model
        info["tool"] = info.get("tool") or "opencode"
    if resume or info.get("session_id"):
        cmd = oc_ops.resume_cmd(info)
    else:
        cmd = oc_ops.start_cmd(info, model)
    cwd = ""
    if side == "trigger":
        cwd = str(opsdir.prepare(data))
    elif not (data.get("runtime") or {}).get("server"):
        directory = (data.get("runtime") or {}).get("directory") or ""
        if directory and Path(directory).expanduser().is_dir():
            cwd = str(Path(directory).expanduser())
    sent = tmux_ops.ensure_agent(tmux_name, cmd, cwd=cwd)
    if sent:
        ui.ok(f"{side} {cmd} -> {tmux_name}" + (f"  cwd={cwd}" if cwd else ""))
    else:
        ui.skip(f"{tmux_name} already running {info.get('tool') or 'agent'}")


def _touch_point(data: dict, which: str) -> None:
    tmux_name = data["op"] if which == "op" else data["run"]
    point = wp.discover(tmux_name)
    data[f"{which}_point"] = point
    if which == "run":
        wp.apply_runtime(data, point)
    save(find_dt(data["name"]), data)
    hub.push_best_effort()


def cmd_enter(args: argparse.Namespace) -> None:
    if not args.name and not iter_dt_files():
        print_next_after_init()
        return
    data = _resolve(args.name)
    hub.require_active(data, force=bool(getattr(args, "force", False)))
    opsdir.prepare(data)
    ev.emit("dt.enter", name=data["name"], oc=bool(getattr(args, "oc", False)))
    wp.stamp(data, "enter_at")
    if getattr(args, "oc", False) or getattr(args, "resume", False):
        _start_side(
            data,
            data["op"],
            "trigger",
            getattr(args, "model", "") or "",
            getattr(args, "resume", False),
        )
        wp.stamp(data, "trigger_oc_at")
    _touch_point(data, "op")
    tmux_ops.attach(data["op"])


def cmd_work(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    hub.require_active(data, force=bool(getattr(args, "force", False)))
    ev.emit("dt.work", name=data["name"], oc=bool(getattr(args, "oc", False)))
    wp.stamp(data, "work_at")
    if getattr(args, "oc", False) or getattr(args, "resume", False):
        _start_side(
            data,
            data["run"],
            "bullet",
            getattr(args, "model", "") or "",
            getattr(args, "resume", False),
        )
        wp.stamp(data, "bullet_oc_at")
    _touch_point(data, "run")
    tmux_ops.attach(data["run"])


def cmd_re(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    cmd = (data.get("runtime") or {}).get("cmd") or ""
    if not cmd:
        raise SystemExit("[err] tunnel has no runtime.cmd")
    tmux_ops.reconnect(data["run"], cmd)


def cmd_send(args: argparse.Namespace) -> None:
    from .control import ControlError, get_control_service

    try:
        get_control_service().send(args.name, args.text, "bullet")
    except ControlError as exc:
        raise SystemExit(str(exc)) from exc


def _ssh_argv(data: dict) -> list[str]:
    from .sshutil import SshTarget

    cfg = require_config()
    runtime = data.get("runtime") or {}
    server = runtime.get("server") or cfg.server
    port = int(runtime.get("ssh_port") or cfg.ssh_port or 22)
    target = SshTarget(server, port)
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        *target.extra_args,
        target.dest,
    ]


def _freeze_one(data: dict, side: str, tmux_name: str, tool: str, wait: bool) -> bool:
    from . import agentclient

    point = wp.discover(tmux_name)
    if side == "trigger":
        data["op_point"] = point
    other = "bullet" if side == "trigger" else "trigger"
    exclude = (data.get(other) or {}).get("session_id") or ""
    info = tmux_ops.pane_info(tmux_name)
    pane_cmd = info.get("cmd") or ""
    side_info = _side(data, side)
    requested_tool = (
        (side_info.get("tool") or "opencode") if tool in {"", "auto"} else tool
    )
    process_commands = [pane_cmd, *wp.walk_commands(info.get("pid") or "")]
    live_transport = pane_cmd in {"ssh", "docker"} or any(
        command.startswith("ssh ")
        or " ssh " in f" {command} "
        or command.startswith("docker exec ")
        for command in process_commands
    )
    if (
        side == "bullet"
        and live_transport
        and point.get("kind") in {"ssh", "docker"}
    ):
        wp.apply_runtime(data, point)
        point = wp.canonical_runtime_point(data, point)
    if side == "bullet":
        data["run_point"] = point
    actual_local_client = agentclient.detect_name(process_commands)
    client_name = actual_local_client or agentclient.normalize_name(requested_tool)
    location = "local" if actual_local_client else point.get("kind") or "local"
    if location not in {"ssh", "docker"}:
        location = "local"
    runtime = data.get("runtime") or {}
    client_meta = agentclient.collect(
        client_name,
        location=location,
        ssh_argv=_ssh_argv(data) if location in {"ssh", "docker"} else None,
        host=runtime.get("server") or point.get("ssh") or "",
        container=point.get("container") or runtime.get("container") or "",
    )
    side_info["agent_client"] = client_meta
    if client_name:
        previous_tool = side_info.get("tool") or ""
        side_info["tool"] = client_name
        from .paneparse import parser_id_for_side

        if previous_tool != client_name:
            side_info["parser"] = ""
            for key in (
                "model",
                "session_id",
                "slug",
                "agent",
                "directory",
                "frozen_at",
            ):
                side_info[key] = ""
        if client_name in {"codex", "claude"}:
            for key in ("model", "session_id", "slug", "agent", "directory", "frozen_at"):
                side_info[key] = ""
        side_info["parser"] = parser_id_for_side(side_info)
    ev.emit(
        "freeze.client.ok" if not client_meta.get("error") else "freeze.client.fail",
        name=data.get("name"),
        side=side,
        client=client_meta.get("name"),
        version=client_meta.get("version"),
        location=client_meta.get("location"),
        error=client_meta.get("error"),
    )
    if client_name in {"codex", "claude"}:
        from . import agent_sessions

        if location in {"ssh", "docker"}:
            session = agent_sessions.discover_remote(
                client_name,
                _ssh_argv(data),
                container=point.get("container") or runtime.get("container") or "",
                cwd=(
                    point.get("directory")
                    or point.get("cwd")
                    or runtime.get("directory")
                    or ""
                ),
            )
        else:
            session = agent_sessions.discover_local(
                client_name,
                pid=info.get("pid") or "",
                commands=process_commands,
                cwd=point.get("cwd") or info.get("cwd") or "",
            )
        if side == "bullet":
            if point.get("kind") == "local" or live_transport:
                wp.capture_runtime(data, point)
            write_entry(data["run"], (data.get("runtime") or {}).get("cmd") or "")
        if not session:
            ui.warn(
                f"no provable {side} {client_name} session on {tmux_name}; not binding historical session"
            )
            return False
        _bind_oc(data, side, session, client_name)
        data[side]["agent_client"] = client_meta
        ev.emit(
            "freeze.side.ok",
            name=data.get("name"),
            side=side,
            tmux=tmux_name,
            session=session.session_id,
            model=session.model,
            client=client_name,
            client_version=client_meta.get("version"),
            cwd=session.directory or point.get("cwd"),
            point_kind=point.get("kind"),
            ssh=point.get("ssh"),
            container=point.get("container"),
            hops=len(point.get("hops") or []),
        )
        _print_side(side, data[side])
        return True
    if client_name and client_name != "opencode":
        ui.warn(f"unsupported {side} agent client: {client_name}")
        return False
    local_oc = pane_cmd == "opencode"
    session = oc_ops.from_pane(
        info.get("pid") or "",
        point.get("cwd") or "",
        exclude,
        fallback=local_oc,
    )
    if wait and not session:
        import time

        deadline = time.time() + 20
        while time.time() < deadline and not session:
            time.sleep(1)
            info = tmux_ops.pane_info(tmux_name)
            pane_cmd = info.get("cmd") or ""
            local_oc = pane_cmd == "opencode"
            session = oc_ops.from_pane(
                info.get("pid") or "", info.get("cwd") or "", exclude, fallback=local_oc
            )
    if (
        not session
        and not local_oc
        and live_transport
        and point["kind"] in {"ssh", "docker"}
    ):
        session = oc_ops.active_remote(
            _ssh_argv(data), point.get("container") or runtime.get("container") or ""
        )
    if not session:
        error = (
            f"no {side} opencode on {tmux_name} "
            f"(cmd={point.get('cmd') or '—'} cwd={point.get('cwd') or '—'})"
        )
        ev.emit(
            "freeze.side.fail",
            name=data.get("name"),
            side=side,
            tmux=tmux_name,
            cmd=point.get("cmd"),
            cwd=point.get("cwd"),
            point_kind=point.get("kind"),
            error=error,
        )
        ui.warn(f"{error}. dt {'enter' if side == 'trigger' else 'work'} --oc first")
        return False
    if side == "bullet":
        if point.get("kind") == "local" or live_transport:
            wp.capture_runtime(data, point)
        write_entry(data["run"], (data.get("runtime") or {}).get("cmd") or "")
    _bind_oc(data, side, session, client_name or "opencode")
    data[side]["agent_client"] = client_meta
    ev.emit(
        "freeze.side.ok",
        name=data.get("name"),
        side=side,
        tmux=tmux_name,
        session=session.session_id,
        model=session.model,
        client=client_meta.get("name"),
        client_version=client_meta.get("version"),
        cwd=point.get("cwd"),
        point_kind=point.get("kind"),
        ssh=point.get("ssh"),
        container=point.get("container"),
        hops=len(point.get("hops") or []),
    )
    _print_side(side, data[side])
    return True


def freeze_sides(
    data: dict, sides: list[str], tool: str = "auto", wait: bool = False
) -> None:
    if "trigger" in sides:
        _freeze_one(data, "trigger", data["op"], tool, wait)
    if "bullet" in sides:
        _freeze_one(data, "bullet", data["run"], tool, wait)


def _apply_model_legacy(name: str, model: str, sides: list[str]) -> dict:
    data = _resolve(name)
    hub.require_active(data)
    model = (model or "").strip()
    if not model:
        raise SystemExit("usage: dt model <name> [--run|--op] <provider/id>")
    ok, detail = oc_ops.probe_model(model)
    if not ok:
        raise SystemExit(f"[err] model probe failed {model}: {detail}")
    ui.ok(f"probe {model}")
    if not sides:
        sides = ["bullet"]
    path = find_dt(data["name"])
    for side in sides:
        tmux_name = data["op"] if side == "trigger" else data["run"]
        info = _side(data, side)
        info["model"] = model
        info["tool"] = info.get("tool") or "opencode"
        if tmux_ops.pane_command(tmux_name) == "opencode":
            ui.info(f"quit {tmux_name} opencode")
            tmux_ops.quit_opencode(tmux_name)
        cmd = oc_ops.start_cmd(info, model)
        cwd = str(opsdir.prepare(data)) if side == "trigger" else ""
        tmux_ops.ensure_agent(tmux_name, cmd, cwd=cwd)
        ui.ok(f"{side} {cmd} -> {tmux_name}")
    save(path, data)
    ui.info("waiting for opencode")
    freeze_sides(data, sides, "opencode", wait=True)
    wp.stamp(data, "freeze_at")
    save(path, data)
    hub.push_best_effort(wait=True)
    return load(path)


def apply_model(name: str, model: str, sides: list[str]) -> dict:
    from .control import ControlError, get_control_service

    try:
        return get_control_service().model(name, model, sides).data
    except ControlError as exc:
        raise SystemExit(str(exc)) from exc


def _apply_freeze_legacy(name: str, sides: list[str] | None = None, tool: str = "auto") -> dict:
    data = _resolve(name)
    path = find_dt(data["name"])
    if not sides:
        sides = ["trigger", "bullet"]
    span = ev.timed("freeze", name=data["name"], sides=",".join(sides))
    freeze_sides(data, sides, tool or "auto")
    wp.stamp(data, "freeze_at")
    save(path, data)
    dst = oc_ops.is_dst(data)
    span.ok(
        is_dst=dst,
        trigger=(data.get("trigger") or {}).get("session_id") or "",
        bullet=(data.get("bullet") or {}).get("session_id") or "",
    )
    hub.push_best_effort(wait=True)
    return load(path)


def apply_freeze(name: str, sides: list[str] | None = None, tool: str = "auto") -> dict:
    from .control import ControlError, get_control_service

    try:
        return get_control_service().freeze(name, sides, tool).data
    except ControlError as exc:
        raise SystemExit(str(exc)) from exc


def cmd_model(args: argparse.Namespace) -> None:
    model = (getattr(args, "model_flag", "") or args.model or "").strip()
    sides: list[str] = []
    if args.op:
        sides.append("trigger")
    if args.run or (not args.op and not args.run):
        sides.append("bullet")
    data = apply_model(args.name, model, sides)
    print_inspect(data)


def cmd_freeze(args: argparse.Namespace) -> None:
    sides: list[str] = []
    if args.trigger or (not args.trigger and not args.bullet):
        sides.append("trigger")
    if args.bullet or (not args.trigger and not args.bullet):
        sides.append("bullet")
    data = apply_freeze(args.name, sides, getattr(args, "tool", "") or "auto")
    dst = oc_ops.is_dst(data)
    ui.ok(f"freeze {data['name']}  IS_DST={'yes' if dst else 'no'}")
    if not dst:
        ui.warn("DST needs both op-oc and run-oc session ids")
    print_inspect(data)


def cmd_capture(args: argparse.Namespace) -> None:
    cmd_freeze(args)


def cmd_make(args: argparse.Namespace) -> None:
    if args.target != "dst":
        raise SystemExit("usage: dt make dst <name> [--tool opencode] [--model ...]")
    name = args.name
    if not name:
        raise SystemExit("usage: dt make dst <name>")
    try:
        find_dt(name)
    except SystemExit:
        cmd_new(
            argparse.Namespace(
                name=name,
                op=None,
                run=None,
                server="",
                container=getattr(args, "container", "") or "",
                dir=getattr(args, "dir", "") or "",
                cmd="",
            )
        )
    path = find_dt(name)
    data = load(path)
    trigger = _side(data, "trigger")
    bullet = _side(data, "bullet")
    tool = args.tool or "opencode"
    model = args.model or ""
    trigger["tool"] = tool
    bullet["tool"] = tool
    if model:
        trigger["model"] = model
        bullet["model"] = model
    if args.trigger_model:
        trigger["model"] = args.trigger_model
    if args.bullet_model:
        bullet["model"] = args.bullet_model
    save(path, data)
    _start_side(data, data["op"], "trigger", trigger.get("model") or "", False)
    _start_side(data, data["run"], "bullet", bullet.get("model") or "", False)
    save(path, data)
    ui.info("waiting for both opencode sessions")
    freeze_sides(data, ["trigger", "bullet"], tool, wait=True)
    save(path, data)
    if not oc_ops.is_dst(data):
        raise SystemExit(
            "[err] DST not ready. dt enter --oc / dt work --oc, then dt freeze"
        )
    ui.ok(f"DST {data['name']}")
    print_inspect(data)
    hub.push_best_effort(wait=True)


def _apply_resume_legacy(name: str | None, force: bool = False) -> dict:
    """Resume a DST without attaching; shared by the CLI and local web UI."""
    data = _resolve(name)
    hub.require_active(data, force=force)
    opsdir.prepare(data)
    if not oc_ops.is_dst(data):
        raise SystemExit("[err] not a DST. Freeze both oc sessions first: dt freeze")
    runtime = data.get("runtime") or {}
    jump = runtime.get("cmd") or ""
    remote_bullet = bool(runtime.get("server"))
    if remote_bullet and not jump:
        raise SystemExit("[err] bullet runtime has a server but no reconnect command")
    transports = {"ssh", "docker"}
    if remote_bullet and tmux_ops.pane_command(data["run"]) not in transports:
        tmux_ops.reconnect(data["run"], jump)
        landed = tmux_ops.wait_stable_command(
            data["run"], transports, timeout=25
        )
        if landed not in transports:
            raise SystemExit(
                f"[err] bullet jump did not stay connected (cmd={landed or '—'}); "
                "resume stopped before sending the session command"
            )
    if remote_bullet:
        from .recovery import ensure_remote_session

        if ensure_remote_session(data):
            ui.ok("imported remote bullet persist JSON")
    trigger = _side(data, "trigger")
    bullet = _side(data, "bullet")
    if (trigger.get("tool") or "opencode") == "opencode" and oc_ops.ensure_local(trigger):
        ui.ok("imported trigger persist JSON")
    if (
        not remote_bullet
        and (bullet.get("tool") or "opencode") == "opencode"
        and oc_ops.ensure_local(bullet, role="bullet")
    ):
        ui.ok("imported local bullet persist JSON")
    _start_side(data, data["op"], "trigger", "", True)
    _start_side(data, data["run"], "bullet", "", True)
    wp.stamp(data, "resume_at")
    data["op_point"] = wp.discover(data["op"])
    data["run_point"] = wp.canonical_runtime_point(
        data, wp.discover(data["run"])
    )
    save(find_dt(data["name"]), data)
    ev.emit("dt.resume", name=data["name"])
    hub.push_best_effort()
    return data


def apply_resume(name: str | None, force: bool = False) -> dict:
    from .control import ControlError, get_control_service

    try:
        return get_control_service().resume(name, force).data
    except ControlError as exc:
        raise SystemExit(str(exc)) from exc


def cmd_resume(args: argparse.Namespace) -> None:
    data = apply_resume(args.name, force=bool(getattr(args, "force", False)))
    ui.ok(f"resumed DST {data['name']}")
    if getattr(args, "attach", True):
        tmux_ops.attach(data["op"])


def _prompt(label: str) -> str:
    try:
        return input(label).strip()
    except EOFError:
        return ""


def prompt_init(workspace: str = "/workspace") -> None:
    if not sys.stdin.isatty():
        raise SystemExit(
            "usage: dt config --init --local --client tm_<id>  "
            "(or add --server <ssh-host> --user <name>)"
        )
    print("First-time setup. dual-tmux does not write SSH keys or ~/.ssh/config.")
    print(f"client: {SOURCE_HINT}")
    print("mode:   local (no SSH) or hub (cross-Client synchronization)")
    client = _prompt("client (tm_*): ")
    mode = (_prompt("mode [local/hub] (local): ") or "local").lower()
    if mode in {"local", "l"}:
        local_workspace = str(Path.cwd()) if workspace == "/workspace" else workspace
        candidate = make_config(client, workspace=local_workspace)
        current = load_config() if config_path().is_file() else None
        path = switch_config(current, candidate) if current else write_config(candidate)
        cfg = load_config()
        ui.ok(f"wrote {path}")
        ui.info(f"client={cfg.client}  mode=local-only  workspace={cfg.workspace}")
        ui.print_next_init()
        _run_hotfix(cfg, ssh=False)
        return
    if mode not in {"hub", "h"}:
        raise SystemExit("[err] mode must be local or hub")
    print("server: Host alias, user@host, or paste `ssh -p 22 root@IP`")
    hosts = list_ssh_hosts()
    if hosts:
        shown = "  ".join(hosts[:12])
        extra = f"  (+{len(hosts) - 12} more)" if len(hosts) > 12 else ""
        print(f"        known aliases: {shown}{extra}")
    else:
        print("        no Host aliases in ~/.ssh/config; add one yourself first")
    print(f"user:   {USER_HINT}")
    print("        local persist  ~/sessions")
    print("        remote persist ~/<user>/sessions")
    print("workspace stays /workspace; override later with dt new --dir")
    server = _prompt("server (alias or ssh ...): ")
    user = _prompt("user: ")
    candidate = make_config(client, server, user, workspace or "/workspace")
    current = load_config() if config_path().is_file() else None
    path = switch_config(current, candidate)
    cfg = load_config()
    ui.ok(f"wrote {path}")
    ui.info(f"client={cfg.client}  server={cfg.server}  user={cfg.user}")
    if cfg.ssh_port != 22:
        ui.info(f"ssh_port={cfg.ssh_port}  (not written to ~/.ssh)")
    ui.info(f"remote persist {remote_sessions_root(cfg.user)}")
    hint = (
        f"ssh -p {cfg.ssh_port} {cfg.server}"
        if cfg.ssh_port != 22
        else f"ssh {cfg.server}"
    )
    ui.print_next_init()
    ui.info(f"then: {hint} && dt doctor")
    _run_hotfix(cfg, ssh=True)


def cmd_config(args: argparse.Namespace) -> None:
    if args.init:
        if not args.client:
            prompt_init(args.workspace or "/workspace")
            return
        if args.local and (args.server or args.user):
            raise SystemExit("[err] --local cannot be combined with --server/--user")
        if not args.local and bool(args.server) != bool(args.user):
            raise SystemExit(
                "[err] --server and --user are required together; or pass --local"
            )
        workspace = args.workspace or (str(Path.cwd()) if args.local else "/workspace")
        candidate = make_config(args.client, args.server, args.user, workspace)
        current = load_config() if config_path().is_file() else None
        path = (
            switch_config(current, candidate)
            if candidate.hub_enabled or current
            else init_config(candidate.client, workspace=candidate.workspace)
        )
        cfg = load_config()
        ui.ok(f"wrote {path}")
        ui.info(f"client={cfg.client}  mode={cfg.mode}")
        if not cfg.hub_enabled:
            ui.info("local-only: no SSH, rsync, or distributed locks")
            _run_hotfix(cfg, ssh=False)
            ui.print_next_init()
            return
        ui.info(f"server={cfg.server}  user={cfg.user}")
        if cfg.ssh_port != 22:
            ui.info(f"ssh_port={cfg.ssh_port}  (not written to ~/.ssh)")
        ui.info(f"remote persist {remote_sessions_root(cfg.user)}")
        hint = (
            f"ssh -p {cfg.ssh_port} {cfg.server}"
            if cfg.ssh_port != 22
            else f"ssh {cfg.server}"
        )
        ui.info(f"next: {hint} && dt doctor")
        _run_hotfix(cfg, ssh=True)
        return
    path = config_path()
    if not path.is_file():
        ui.warn(f"config {path} missing")
        ui.info("dt config --init --client tm_laptop --server myserver --user ouc")
        return
    cfg = load_config()
    ui.info(f"home       {home_dir()}")
    ui.info(f"config     {path}")
    ui.info(f"client     {cfg.client}")
    ui.info(f"mode       {cfg.mode}")
    if cfg.hub_enabled:
        ui.info(f"server     {cfg.server}")
        if cfg.ssh_port != 22:
            ui.info(f"ssh_port   {cfg.ssh_port}")
        ui.info(f"user       {cfg.user}")
        ui.info(f"remote     {remote_sessions_root(cfg.user)}")
        ui.info(f"hub        {remote_dt_root(cfg.user)}")
    else:
        ui.info("hub        — (attach: dt config --server HOST --user NAME)")
    ui.info(f"workspace  {cfg.workspace}")
    changing = (
        args.local or args.client or args.server or args.user or bool(args.workspace)
    )
    if changing:
        if args.local and (args.server or args.user):
            raise SystemExit("[err] --local cannot be combined with --server/--user")
        server = "" if args.local else (args.server or cfg.server)
        user = "" if args.local else (args.user or cfg.user)
        workspace = args.workspace or cfg.workspace
        if not args.workspace and args.local and cfg.hub_enabled:
            workspace = str(Path.cwd())
        elif not args.workspace and args.server and not cfg.hub_enabled:
            workspace = "/workspace"
        candidate = make_config(
            args.client or cfg.client,
            server,
            user,
            workspace,
        )
        path = switch_config(cfg, candidate)
        ui.ok(f"merged records and switched to {candidate.mode} config  {path}")
        _run_hotfix(candidate, ssh=candidate.hub_enabled)


def cmd_tick(_: argparse.Namespace) -> None:
    from . import recovery
    from .feishu import FeishuError
    from .feishu_bridge import sync_client

    cfg = require_config()
    hub.enforce_local()
    n = 0
    seen: list[dict] = []
    for path in iter_dt_files():
        data = load(path)
        seen.append(data)
        name = data.get("name") or path.stem
        live = tmux_ops.has_session(data.get("op") or "") or tmux_ops.has_session(
            data.get("run") or ""
        )
        if not live and not data.get("auto_recover"):
            continue
        if not cfg.hub_enabled and (data.get("runtime") or {}).get("server"):
            continue
        try:
            holder, _age = hub.read_lock(name)
        except SystemExit:
            holder = ""
        if holder and holder != cfg.client:
            hub.drop_local(data)
            continue
        activity.append_sample(data)
        try:
            hub.claim(name)
        except SystemExit:
            continue
        recovery.observe(data)
        n += 1
    hub.sync_best_effort(wait=True)
    statusbar.refresh(seen, hub_enabled=cfg.hub_enabled)
    try:
        sync_client(cfg)
    except (FeishuError, SystemExit, OSError) as exc:
        ev.emit("feishu.bridge.sync.reject", reason=type(exc).__name__)
    ui.ok(f"tick  {n} live DT  log={activity.activity_path()}")


def cmd_health(args: argparse.Namespace) -> None:
    from . import recovery

    cfg = require_config()
    records = [_resolve(args.name)] if args.name else [load(p) for p in iter_dt_files()]
    rows = []
    for data in records:
        if not cfg.hub_enabled and (data.get("runtime") or {}).get("server"):
            rows.append(recovery.read_state(data.get("name") or ""))
        else:
            rows.append(recovery.observe(data, auto=False))
    payload: object = rows[0] if args.name else rows
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for row in rows:
        ui.info(
            f"{row.get('name')}  {row.get('status')}  "
            f"failures={row.get('last_error') or '—'}"
        )


def cmd_recover(args: argparse.Namespace) -> None:
    from . import recovery

    data = _resolve(args.name)
    name = data["name"]
    if args.enable:
        recovery.set_enabled(name, True)
        ui.ok(f"auto recovery enabled  {name}")
    elif args.disable:
        recovery.set_enabled(name, False)
        ui.ok(f"auto recovery disabled  {name}")
    elif args.now:
        result = recovery.recover_now(data, force=args.force)
        if not result.get("healthy"):
            raise SystemExit(
                f"[err] recovery verification failed: "
                f"{','.join(result.get('failures') or [])}"
            )
        recovery.observe(data, auto=False, prober=lambda _: result)
        ui.ok(f"recovered  {name}")
    else:
        print(json.dumps(recovery.read_state(name), ensure_ascii=False, indent=2))


def cmd_drop(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    hub.drop_local(data)
    try:
        hub.release(data["name"])
        if require_config().hub_enabled:
            ui.ok(f"released {data['name']}  (hub binding kept)")
        else:
            ui.ok(f"dropped {data['name']}  (local binding kept)")
    except SystemExit as exc:
        ui.warn(str(exc))


def cmd_park(args: argparse.Namespace) -> None:
    cmd_drop(args)


def _run_hotfix(cfg=None, *, ssh: bool = True) -> None:
    try:
        steps = hotfix_ops.apply(cfg, ssh=ssh)
    except SystemExit as exc:
        ui.warn(str(exc))
        return
    for step in steps:
        msg = f"{step.id}  {step.detail}"
        if not step.ok:
            ui.warn(msg)
        elif step.changed:
            ui.ok(msg)
        else:
            ui.skip(msg)


def cmd_doctor(_: argparse.Namespace) -> None:
    cfg = None
    try:
        cfg = load_config()
    except Exception:
        cfg = None
    if cfg and cfg.client.startswith("tm_"):
        _run_hotfix(cfg, ssh=True)
    else:
        try:
            if cron_ops.install():
                ui.ok(f"crontab  {cron_ops.line()}")
        except SystemExit as exc:
            ui.warn(str(exc))
    _, checks = collect_checks()
    ok = print_checks(checks)
    ui.info(f"tunnels  {len(iter_dt_files())}")
    try:
        hub.enforce_local()
    except SystemExit:
        pass
    if not ok:
        guide_if_needed(checks)
        raise SystemExit(1)


def cmd_rm(args: argparse.Namespace) -> None:
    path = find_dt(args.name)
    data = load(path)
    name = data["name"]
    op = data.get("op") or ""
    run = data.get("run") or ""
    if not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("usage: dt rm <name> --yes [--kill]")
        answer = (
            input(f"rm {name}  op={op}  run={run}  kill_tmux={args.kill}? [y/N] ")
            .strip()
            .lower()
        )
        if answer not in {"y", "yes"}:
            ui.skip("cancelled")
            return
    try:
        hub.release(name)
    except SystemExit:
        pass
    data = remove_dt(name)
    opsdir.remove_ops(op)
    killed = []
    if args.kill:
        if tmux_ops.kill_session(op):
            killed.append(op)
        if tmux_ops.kill_session(run):
            killed.append(run)
    ev.emit("dt.rm", name=name, op=op, run=run, kill=args.kill, killed=",".join(killed))
    ui.ok(f"removed {name}")
    if killed:
        ui.info(f"killed tmux  {' '.join(killed)}")
    else:
        ui.info("tmux sessions kept (pass --kill to destroy op_*/run_*)")
    ui.info("OpenCode sqlite untouched")
    try:
        hub.remove_remote(name, run)
        ui.info("hub removed tunnel json")
    except SystemExit as exc:
        ui.warn(f"hub rm skipped  {exc}")


def cmd_push(_: argparse.Namespace) -> None:
    dest = hub.push()
    statusbar.write_state(True, dest)
    statusbar.refresh([load(p) for p in iter_dt_files()])
    ui.ok(f"pushed tunnels+entries → {dest}")
    ui.info("config.toml / ops / events stay on this Client")


def cmd_pull(_: argparse.Namespace) -> None:
    dest = hub.pull()
    statusbar.refresh([load(p) for p in iter_dt_files()])
    ui.ok(f"pulled tunnels+entries ← {dest}")
    ui.info(f"this Client stays {require_config().client}")


def cmd_log(args: argparse.Namespace) -> None:
    rows = ev.read_events(limit=args.limit, kind=args.kind, name=args.name or "")
    ui.print_log(rows)


def cmd_cron(args: argparse.Namespace) -> None:
    if args.remove:
        if cron_ops.uninstall():
            ui.ok("removed dt tick from crontab")
        else:
            ui.skip("no dt tick crontab")
        return
    if cron_ops.install():
        ui.ok(f"crontab  {cron_ops.line()}")
    else:
        ui.skip(f"already  {cron_ops.line()}")


def _print_facts(data: dict, label: str) -> None:
    ui.info(label)
    facts = data.get("facts") or {}
    if not facts:
        ui.skip("(empty facts)")
        return
    print(json.dumps(facts, ensure_ascii=False, indent=2))


def cmd_mem(args: argparse.Namespace) -> None:
    name = args.name or ""
    action = args.action or "get"
    if action == "set":
        if not args.key:
            raise SystemExit("usage: dt mem [name] set <key> <value>")
        data = mem_ops.put_fact(args.key, args.value, name or None)
        ui.ok(f"set {args.key}")
        _print_facts(
            data,
            f"{name or 'shared'}  {mem_ops.agent_memory_path(name) if name else mem_ops.global_memory_path()}",
        )
        return
    if name:
        mem_ops.ensure_agent(name)
        _print_facts(mem_ops.get_memory(name), str(mem_ops.agent_memory_path(name)))
        return
    _print_facts(mem_ops.get_memory(), str(mem_ops.global_memory_path()))


def cmd_note(args: argparse.Namespace) -> None:
    row = mem_ops.add_note(
        args.name,
        args.body,
        title=args.title or "",
        kind=args.kind or "note",
        day=args.day or "",
    )
    ui.ok(f"note {row['id']}  {row['day']}  {row['kind']}")


def cmd_notes(args: argparse.Namespace) -> None:
    rows = mem_ops.query_notes(
        args.name,
        day=args.day or "",
        since=args.since or "",
        until=args.until or "",
        q=args.q or "",
        limit=args.limit,
    )
    if not rows:
        ui.skip("(no notes)")
        return
    for row in rows:
        title = row.get("title") or ""
        head = f"#{row['id']}  {row['day']}  {row['kind']}"
        if title:
            head += f"  {title}"
        ui.info(head)
        print(row.get("body") or "")


def cmd_skill(args: argparse.Namespace) -> None:
    action = args.skill_cmd or "ls"
    if action == "ls":
        rows = skillmgr.list_catalog()
        if not rows:
            ui.skip("no skills in ~/.dual-tmux/skills")
            return
        for row in rows:
            flags = []
            if row["trigger"]:
                flags.append("trigger")
            if row["bullet"]:
                flags.append("bullet")
            mark = ",".join(flags) or "-"
            ui.info(f"{row['name']}  [{mark}]  {row['description'][:80]}")
        return
    if action == "import":
        name = skillmgr.import_skill(args.path)
        ui.ok(f"imported {name} → {skillmgr.catalog_dir() / name}")
        return
    if action == "enable":
        skillmgr.set_enabled(args.name, args.who, True)
        ui.ok(f"enable {args.name} on {args.who}")
        return
    if action == "disable":
        skillmgr.set_enabled(args.name, args.who, False)
        ui.ok(f"disable {args.name} on {args.who}")
        return
    if action == "teach":
        from . import tmux as tmux_ops

        data = _resolve(args.dt)
        msg = skillmgr.teach(data["name"], args.skills, args.text or "")
        tmux_ops.send_keys(data["run"], msg)
        ui.ok(f"taught {', '.join(args.skills)} → {data['run']}")
        return
    if action == "used":
        ok = True if args.ok else False if args.fail else True
        skillmgr.log_use(args.dt, args.name, ok, args.detail or "")
        ui.ok(f"logged {args.name}  ok={ok}")
        return
    if action == "log":
        rows = skillmgr.read_log(
            limit=args.limit,
            skill=args.name or "",
            name=args.dt or "",
            ok=args.status or "",
        )
        if not rows:
            ui.skip("(no skill usage)")
            return
        for row in rows:
            flag = "ok" if row.get("ok") else "fail"
            ui.info(
                f"{row.get('ts')}  {flag}  {row.get('dt')}  {row.get('who')}  {row.get('skill')}  {row.get('detail') or ''}"
            )
        return
    raise SystemExit("usage: dt skill ls|import|enable|disable|teach|used|log")


def cmd_hotfix(_: argparse.Namespace) -> None:
    if not config_path().is_file():
        ui.warn("no config; dt config --init first")
        return
    _run_hotfix(load_config(), ssh=True)
    ui.ok(f"hotfix {hotfix_ops.HOTFIX_ID}")


def cmd_web(args: argparse.Namespace) -> None:
    from .web import DEFAULT_PORT, HOST, serve

    port = int(args.port or DEFAULT_PORT)
    ui.info(f"http://{HOST}:{port}")
    serve(HOST, port, open_browser=not args.no_open)


def cmd_daemon(args: argparse.Namespace) -> None:
    from . import daemon_service
    from .daemon import read_daemon_status, serve

    if args.install:
        ui.ok(f"daemon installed  {daemon_service.install()}")
        return
    if args.remove:
        ui.ok("daemon removed" if daemon_service.uninstall() else "daemon not installed")
        return
    if args.status:
        print(json.dumps(read_daemon_status(), ensure_ascii=False, indent=2))
        return
    serve(once=bool(args.once))


def cmd_upgrade(_: argparse.Namespace) -> None:
    ui.info(f"Current version: {__version__}")
    try:
        from .upgrade import install_latest

        asset = install_latest(__version__)
        ui.ok(f"GitHub Release  {asset.tag} ({asset.version})")
    except (OSError, RuntimeError, ValueError) as exc:
        ui.warn(f"GitHub Release discovery failed; using uv fallback: {exc}")
        result = subprocess.run(
            ["uv", "tool", "upgrade", "dual-tmux"],
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(result.returncode)
    dt = shutil.which("dt") or str(Path.home() / ".local" / "bin" / "dt")
    os.execv(dt, [dt, "hotfix"])


def cmd_feishu(args: argparse.Namespace) -> None:
    from .feishu import (
        AppRegistrationService,
        FeishuDispatcher,
        FeishuError,
        OperatorIdentity,
        status,
        unbind_operator,
        uninstall,
    )

    try:
        if args.feishu_cmd == "status":
            result = status()
        elif args.feishu_cmd == "pair":
            result = AppRegistrationService().begin()
        elif args.feishu_cmd == "poll":
            result = AppRegistrationService().poll()
        elif args.feishu_cmd == "unbind":
            result = uninstall() if not args.identity else {"removed": unbind_operator(args.identity)}
        elif args.feishu_cmd == "dispatch":
            identity = OperatorIdentity(
                open_id=args.open_id,
                union_id=args.union_id,
                user_id=args.user_id,
            )
            result = FeishuDispatcher().dispatch(args.event_id, identity, args.message)
        elif args.feishu_cmd == "sync":
            from .feishu_bridge import sync_client

            result = sync_client()
        else:
            raise FeishuError("invalid_command", "choose a dt feishu subcommand")
    except FeishuError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dt",
        description="DT = op_*/run_* tmux pair. DST = that pair plus trigger/bullet OpenCode sessions.",
    )
    parser.add_argument("--version", action="store_true", help="show version")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("ls", help="list DT; second column is IS_DST")
    p_show = sub.add_parser("show", help="show one tunnel JSON")
    p_show.add_argument("name")
    p_ins = sub.add_parser(
        "inspect", help="show DT/DST fields including empty tool/model/session"
    )
    p_ins.add_argument("name", nargs="?", help="defaults to latest tunnel")

    p_rm = sub.add_parser(
        "rm", help="unregister a DT; --kill also destroys op_*/run_* tmux"
    )
    p_rm.add_argument("name")
    p_rm.add_argument("--yes", "-y", action="store_true", help="do not prompt")
    p_rm.add_argument(
        "--kill", action="store_true", help="tmux kill-session op_* and run_*"
    )

    p_branch = sub.add_parser(
        "branch", help="replay jump + new oc on both sides; freeze as its own DST"
    )
    p_branch.add_argument("src")
    p_branch.add_argument("dest")

    p_new = sub.add_parser("new", help="create op/run sessions and register a tunnel")
    p_new.add_argument("name", help="dt-app or app")
    p_new.add_argument("--op", help="defaults to op_<name>")
    p_new.add_argument("--run", help="defaults to run_<name>")
    p_new.add_argument(
        "--server", default="", help="overrides config server (ssh host)"
    )
    p_new.add_argument(
        "--local", action="store_true", help="force local runtime even in Hub mode"
    )
    p_new.add_argument("--container", default="")
    p_new.add_argument("--dir", default="", help="remote working directory")
    p_new.add_argument("--cmd", default="", help="override reconnect command")

    p_bind = sub.add_parser(
        "bind", help="set DST tool/model/session_id on trigger and bullet"
    )
    p_bind.add_argument("name")
    p_bind.add_argument("--trigger", default="", help="trigger slug")
    p_bind.add_argument("--bullet", default="", help="bullet slug")
    p_bind.add_argument("--trigger-id", default="", help="trigger session id")
    p_bind.add_argument("--bullet-id", default="", help="bullet session id")
    p_bind.add_argument("--trigger-tool", default="", help="default opencode")
    p_bind.add_argument("--bullet-tool", default="", help="default opencode")
    p_bind.add_argument("--trigger-model", default="")
    p_bind.add_argument("--bullet-model", default="")

    for name, help_text in (
        ("enter", "attach op_* (line head on Client)"),
        ("work", "attach run_* (jump to Server workspace)"),
        ("re", "re-send runtime ssh/docker into run_*"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("name", nargs="?", help="defaults to latest tunnel")
        if name in {"enter", "work"}:
            p.add_argument(
                "--oc", action="store_true", help="start OpenCode in that tmux"
            )
            p.add_argument("--model", default="", help="model for --oc")
            p.add_argument(
                "--resume", action="store_true", help="resume by recorded session_id"
            )
            p.add_argument(
                "--force",
                action="store_true",
                help="steal hub lock from another Client",
            )

    p_model = sub.add_parser("model", help="restart a side with a new model and freeze")
    p_model.add_argument("name", nargs="?", help="defaults to latest tunnel")
    p_model.add_argument(
        "model", nargs="?", default="", help="provider/id, e.g. cli-proxy/glm-5.1"
    )
    p_model.add_argument(
        "--model", dest="model_flag", default="", help="same as positional model"
    )
    p_model.add_argument("--run", action="store_true", help="bullet (default)")
    p_model.add_argument("--op", action="store_true", help="trigger")

    p_freeze = sub.add_parser(
        "freeze", help="freeze op-oc and run-oc; DST only if both exist"
    )
    p_freeze.add_argument("name", nargs="?", help="defaults to latest tunnel")
    p_freeze.add_argument("--trigger", action="store_true")
    p_freeze.add_argument("--bullet", action="store_true")
    p_freeze.add_argument(
        "--tool", choices=["auto", "opencode", "codex", "claude"], default="auto"
    )
    p_cap = sub.add_parser("capture", help="alias of freeze")
    p_cap.add_argument("name", nargs="?", help="defaults to latest tunnel")
    p_cap.add_argument("--trigger", action="store_true")
    p_cap.add_argument("--bullet", action="store_true")
    p_cap.add_argument(
        "--tool", choices=["auto", "opencode", "codex", "claude"], default="auto"
    )

    p_make = sub.add_parser(
        "make", help="dt make dst <name> — create DT + both oc and freeze"
    )
    p_make.add_argument("target", choices=["dst"])
    p_make.add_argument("name")
    p_make.add_argument("--tool", default="opencode")
    p_make.add_argument("--model", default="", help="model for both sides")
    p_make.add_argument("--trigger-model", default="")
    p_make.add_argument("--bullet-model", default="")
    p_make.add_argument("--container", default="")
    p_make.add_argument("--dir", default="")

    p_resume = sub.add_parser(
        "resume", help="resume a DST; reconnects missing op/run oc"
    )
    p_resume.add_argument("name", nargs="?", help="defaults to latest tunnel")
    p_resume.add_argument(
        "--force", action="store_true", help="steal hub lock from another Client"
    )

    p_drop = sub.add_parser(
        "drop", help="kill local op_*/run_* and release hub lock; binding stays"
    )
    p_drop.add_argument("name", nargs="?", help="defaults to latest tunnel")
    p_park = sub.add_parser("park", help="alias of dt drop")
    p_park.add_argument("name", nargs="?", help="defaults to latest tunnel")

    p_send = sub.add_parser("send", help="send-keys into run_*")
    p_send.add_argument("name")
    p_send.add_argument("text")

    p_config = sub.add_parser("config", help="show or init Client/Server config")
    p_config.add_argument("--init", action="store_true")
    p_config.add_argument(
        "--local", action="store_true", help="use local-only mode; safely detach a Hub"
    )
    p_config.add_argument(
        "--client", default="", help="legal local source name, must start with tm_"
    )
    p_config.add_argument(
        "--server", default="", help="ssh Host alias already in ~/.ssh/config"
    )
    p_config.add_argument(
        "--user", default="", help="person id; remote persist ~/<user>/sessions"
    )
    p_config.add_argument("--workspace", default="")

    sub.add_parser("push", help="rsync tunnels+entries to Server ~/<user>/dual-tmux")
    sub.add_parser(
        "pull", help="rsync tunnels+entries from Server; keeps this Client config.toml"
    )
    sub.add_parser(
        "tick", help="sample pane fingerprints; renew lock; push activity.log"
    )
    p_health = sub.add_parser("health", help="probe tunnel health; Web reads its cache")
    p_health.add_argument("name", nargs="?", help="all tunnels when omitted")
    p_health.add_argument("--json", action="store_true")
    p_recover = sub.add_parser("recover", help="manage conservative tunnel recovery")
    p_recover.add_argument("name")
    recover_mode = p_recover.add_mutually_exclusive_group()
    recover_mode.add_argument("--enable", action="store_true")
    recover_mode.add_argument("--disable", action="store_true")
    recover_mode.add_argument("--status", action="store_true")
    recover_mode.add_argument("--now", action="store_true")
    p_recover.add_argument(
        "--force", action="store_true", help="steal hub ownership for --now"
    )
    p_cron = sub.add_parser("cron", help="install/remove the minute dt tick crontab")
    p_cron.add_argument("--install", action="store_true", default=True)
    p_cron.add_argument("--remove", action="store_true")

    p_log = sub.add_parser("log", help="show CLI event log (~/.dual-tmux/events.jsonl)")
    p_log.add_argument("-n", "--limit", type=int, default=40)
    p_log.add_argument("--kind", default="", help="prefix filter, e.g. freeze")
    p_log.add_argument("--name", default="", help="filter by DT name")

    p_mem = sub.add_parser("mem", help="shared or per-agent MEMORY.json facts")
    p_mem.add_argument(
        "name",
        nargs="?",
        default="",
        help="dt name; omit for shared ~/.dual-tmux/MEMORY.json",
    )
    p_mem.add_argument("action", nargs="?", default="get", choices=["get", "set"])
    p_mem.add_argument("key", nargs="?", default="")
    p_mem.add_argument("value", nargs="?", default="")

    p_note = sub.add_parser("note", help="append a sqlite note for one agent")
    p_note.add_argument("name", help="dt name")
    p_note.add_argument("body")
    p_note.add_argument("--title", default="")
    p_note.add_argument("--kind", default="note")
    p_note.add_argument("--day", default="", help="YYYY-MM-DD (default today)")

    p_notes = sub.add_parser("notes", help="list/search agent sqlite notes (day + FTS)")
    p_notes.add_argument("name", help="dt name")
    p_notes.add_argument("--day", default="", help="YYYY-MM-DD")
    p_notes.add_argument("--since", default="")
    p_notes.add_argument("--until", default="")
    p_notes.add_argument("--q", default="", help="FTS5 MATCH query")
    p_notes.add_argument("-n", "--limit", type=int, default=40)

    p_skill = sub.add_parser(
        "skill", help="catalog in ~/.dual-tmux/skills; trigger subset; teach bullet"
    )
    sk = p_skill.add_subparsers(dest="skill_cmd")
    sk.add_parser("ls", help="list catalog and who uses each skill")
    p_imp = sk.add_parser(
        "import", help="import folder, SKILL.md, or zip into the catalog"
    )
    p_imp.add_argument("path")
    p_en = sk.add_parser("enable", help="add skill to trigger or bullet subset")
    p_en.add_argument("name")
    p_en.add_argument("who", choices=["trigger", "bullet"])
    p_dis = sk.add_parser("disable", help="remove skill from trigger or bullet subset")
    p_dis.add_argument("name")
    p_dis.add_argument("who", choices=["trigger", "bullet"])
    p_teach = sk.add_parser(
        "teach", help="enable on bullet and send-keys the skill names into run_*"
    )
    p_teach.add_argument("dt")
    p_teach.add_argument("skills", nargs="+")
    p_teach.add_argument("--text", default="", help="override message sent to bullet")
    p_used = sk.add_parser("used", help="log that trigger used a skill")
    p_used.add_argument("dt")
    p_used.add_argument("name")
    p_used.add_argument("--ok", action="store_true")
    p_used.add_argument("--fail", action="store_true")
    p_used.add_argument("--detail", default="")
    p_slog = sk.add_parser("log", help="skill usage log (time, ok/fail)")
    p_slog.add_argument("-n", "--limit", type=int, default=40)
    p_slog.add_argument("--name", default="", help="filter skill")
    p_slog.add_argument("--dt", default="")
    p_slog.add_argument("--status", default="", help="yes|no")
    p_web = sub.add_parser("web", help="local admin UI for tunnel pane I/O")
    p_web.add_argument("--port", type=int, default=8787)
    p_web.add_argument(
        "--no-open", action="store_true", help="do not open the default browser"
    )
    p_daemon = sub.add_parser("daemon", help="run the persistent health/Feishu service")
    daemon_mode = p_daemon.add_mutually_exclusive_group()
    daemon_mode.add_argument("--install", action="store_true", help="install and start the user service")
    daemon_mode.add_argument("--remove", action="store_true", help="stop and remove the user service")
    daemon_mode.add_argument("--status", action="store_true", help="show daemon/connector state")
    daemon_mode.add_argument("--once", action="store_true", help="run one supervisor iteration")
    p_feishu = sub.add_parser(
        "feishu", help="configure secure Feishu pairing and command dispatch"
    )
    fs = p_feishu.add_subparsers(dest="feishu_cmd")
    fs.add_parser("status", help="show configuration and bound operators")
    fs.add_parser("pair", help="create a scan-to-create PersonalAgent QR URL")
    fs.add_parser("poll", help="poll the active scan-to-create registration")
    fs.add_parser("sync", help="exchange callback/command envelopes with the Hub")
    p_fu = fs.add_parser("unbind", help="unbind one identity ID, or all when omitted")
    p_fu.add_argument("identity", nargs="?", default="")
    p_fd = fs.add_parser("dispatch", help="bridge/test one authenticated Feishu event")
    p_fd.add_argument("--event-id", required=True)
    p_fd.add_argument("--open-id", default="")
    p_fd.add_argument("--union-id", default="")
    p_fd.add_argument("--user-id", default="")
    p_fd.add_argument("message", help='for example: "/dt ls"')
    sub.add_parser(
        "doctor", help="check config, tmux, ssh; apply persist tenant hotfix"
    )
    sub.add_parser("hotfix", help="apply persist tenant hotfix without upgrading")
    sub.add_parser("upgrade", help="upgrade via uv tool, then exec dt hotfix")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.version:
        cmd_version(args)
        return
    command = args.command
    if command is None:
        if not config_path().is_file():
            prompt_init()
        ensure_ready()
        cmd_enter(argparse.Namespace(name=None))
        return
    if command not in {
        "config",
        "doctor",
        "hotfix",
        "upgrade",
        "ls",
        "show",
        "inspect",
        "log",
        "tick",
        "health",
        "recover",
        "cron",
        "mem",
        "note",
        "notes",
        "web",
        "skill",
        "feishu",
        "daemon",
    }:
        if not config_path().is_file():
            prompt_init()
        ensure_ready()
    handlers = {
        "ls": cmd_ls,
        "show": cmd_show,
        "inspect": cmd_inspect,
        "new": cmd_new,
        "branch": cmd_branch,
        "rm": cmd_rm,
        "bind": cmd_bind,
        "model": cmd_model,
        "freeze": cmd_freeze,
        "capture": cmd_capture,
        "make": cmd_make,
        "resume": cmd_resume,
        "drop": cmd_drop,
        "park": cmd_park,
        "enter": cmd_enter,
        "work": cmd_work,
        "re": cmd_re,
        "send": cmd_send,
        "config": cmd_config,
        "push": cmd_push,
        "pull": cmd_pull,
        "tick": cmd_tick,
        "health": cmd_health,
        "recover": cmd_recover,
        "cron": cmd_cron,
        "log": cmd_log,
        "doctor": cmd_doctor,
        "mem": cmd_mem,
        "note": cmd_note,
        "notes": cmd_notes,
        "hotfix": cmd_hotfix,
        "web": cmd_web,
        "skill": cmd_skill,
        "feishu": cmd_feishu,
        "daemon": cmd_daemon,
        "upgrade": cmd_upgrade,
    }
    ev.emit("cmd.start", cmd=command)
    try:
        handlers[command](args)
    except SystemExit as exc:
        code = exc.code
        if code not in (0, None):
            ev.emit("cmd.fail", cmd=command, error=str(code))
        raise
    ev.emit("cmd.ok", cmd=command)


if __name__ == "__main__":
    main()
