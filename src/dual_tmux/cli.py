from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys

from . import __version__
from .config import AppConfig, init_config, load_config
from . import oc as oc_ops
from .identity import SOURCE_HINT, USER_HINT, remote_dt_root, remote_sessions_root
from . import hub
from .sshutil import list_ssh_hosts, parse_ssh_target
from .health import collect_checks, ensure_ready, guide_if_needed, print_checks
from .paths import config_path, home_dir, tunnels_dir
from .runtime import build_cmd
from .store import (
    default_names,
    find_dt,
    iter_dt_files,
    latest_dt,
    legal_op,
    legal_run,
    load,
    occupied,
    save,
    write_entry,
    now_iso,
    remove_dt,
)
from . import log as ev
from . import opsdir
from . import tmux as tmux_ops
from . import ui
from . import workpoint as wp


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
    ui.print_ls([load(path) for path in iter_dt_files()])


def cmd_show(args: argparse.Namespace) -> None:
    print(json.dumps(_resolve(args.name), ensure_ascii=False, indent=2))


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
    if args.server:
        target = parse_ssh_target(args.server)
        server = target.dest
        ssh_port = target.port
    else:
        server = cfg.server
        ssh_port = cfg.ssh_port
    directory = args.dir or cfg.workspace
    cmd = args.cmd or build_cmd(server, args.container or "", directory, ssh_port)
    tmux_ops.ensure_session(run)
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
    hub.push_best_effort()


def _side(data: dict, name: str) -> dict:
    side = data.setdefault(name, oc_ops.empty_side())
    side.setdefault("tool", "opencode")
    side.setdefault("model", "")
    side.setdefault("session_id", "")
    side.setdefault("slug", "")
    side.setdefault("agent", "")
    return side


def _bind_oc(data: dict, side: str, session: oc_ops.OcSession, tool: str = "") -> None:
    data[side] = oc_ops.as_bind(session, tool)
    data["updated_at"] = now_iso()


def _print_side(label: str, info: dict) -> None:
    ui.info(
        f"{label}  tool={info.get('tool') or '—'}  "
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
    hub.push_best_effort()


def _resolve(name: str | None) -> dict:
    try:
        path = find_dt(name) if name else latest_dt()
        return load(path)
    except SystemExit:
        if not name:
            raise
        ui.info("tunnel missing locally; pulling hub")
        hub.pull()
        path = find_dt(name)
        return load(path)


def print_next_after_init() -> None:
    ui.print_next_init()


def _start_side(data: dict, tmux_name: str, side: str, model: str = "", resume: bool = False) -> None:
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
    sent = tmux_ops.ensure_agent(tmux_name, cmd, cwd=cwd)
    if sent:
        ui.ok(f"{side} {cmd} -> {tmux_name}" + (f"  cwd={cwd}" if cwd else ""))
    else:
        ui.skip(f"{tmux_name} already running opencode")


def _touch_point(data: dict, which: str) -> None:
    tmux_name = data["op"] if which == "op" else data["run"]
    point = wp.discover(tmux_name)
    data[f"{which}_point"] = point
    if which == "run":
        wp.apply_runtime(data, point)
    save(find_dt(data["name"]), data)


def cmd_enter(args: argparse.Namespace) -> None:
    if not args.name and not iter_dt_files():
        print_next_after_init()
        return
    data = _resolve(args.name)
    opsdir.prepare(data)
    ev.emit("dt.enter", name=data["name"], oc=bool(getattr(args, "oc", False)))
    wp.stamp(data, "enter_at")
    if getattr(args, "oc", False) or getattr(args, "resume", False):
        _start_side(data, data["op"], "trigger", getattr(args, "model", "") or "", getattr(args, "resume", False))
        wp.stamp(data, "trigger_oc_at")
    _touch_point(data, "op")
    tmux_ops.attach(data["op"])


def cmd_work(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    ev.emit("dt.work", name=data["name"], oc=bool(getattr(args, "oc", False)))
    wp.stamp(data, "work_at")
    if getattr(args, "oc", False) or getattr(args, "resume", False):
        _start_side(data, data["run"], "bullet", getattr(args, "model", "") or "", getattr(args, "resume", False))
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
    data = _resolve(args.name)
    tmux_ops.send_keys(data["run"], args.text)


def _ssh_argv(data: dict) -> list[str]:
    from .sshutil import SshTarget

    cfg = require_config()
    runtime = data.get("runtime") or {}
    server = runtime.get("server") or cfg.server
    port = int(runtime.get("ssh_port") or cfg.ssh_port or 22)
    target = SshTarget(server, port)
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", *target.extra_args, target.dest]


def _freeze_one(data: dict, side: str, tmux_name: str, tool: str, wait: bool) -> bool:
    point = wp.discover(tmux_name)
    data["op_point" if side == "trigger" else "run_point"] = point
    if side == "bullet":
        wp.apply_runtime(data, point)
    other = "bullet" if side == "trigger" else "trigger"
    exclude = (data.get(other) or {}).get("session_id") or ""
    info = tmux_ops.pane_info(tmux_name)
    pane_cmd = info.get("cmd") or ""
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
            session = oc_ops.from_pane(info.get("pid") or "", info.get("cwd") or "", exclude, fallback=local_oc)
    if not session and not local_oc and point["kind"] in {"ssh", "docker"}:
        runtime = data.get("runtime") or {}
        session = oc_ops.latest_remote(_ssh_argv(data), point.get("container") or runtime.get("container") or "")
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
    _bind_oc(data, side, session, tool)
    ev.emit(
        "freeze.side.ok",
        name=data.get("name"),
        side=side,
        tmux=tmux_name,
        session=session.session_id,
        model=session.model,
        cwd=point.get("cwd"),
        point_kind=point.get("kind"),
        ssh=point.get("ssh"),
        container=point.get("container"),
        hops=len(point.get("hops") or []),
    )
    _print_side(side, data[side])
    return True


def freeze_sides(data: dict, sides: list[str], tool: str = "opencode", wait: bool = False) -> None:
    if "trigger" in sides:
        _freeze_one(data, "trigger", data["op"], tool, wait)
    if "bullet" in sides:
        _freeze_one(data, "bullet", data["run"], tool, wait)


def cmd_freeze(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    path = find_dt(data["name"])
    sides: list[str] = []
    if args.trigger or (not args.trigger and not args.bullet):
        sides.append("trigger")
    if args.bullet or (not args.trigger and not args.bullet):
        sides.append("bullet")
    span = ev.timed("freeze", name=data["name"], sides=",".join(sides))
    freeze_sides(data, sides, getattr(args, "tool", "") or "opencode")
    wp.stamp(data, "freeze_at")
    save(path, data)
    dst = oc_ops.is_dst(data)
    span.ok(
        is_dst=dst,
        trigger=(data.get("trigger") or {}).get("session_id") or "",
        bullet=(data.get("bullet") or {}).get("session_id") or "",
    )
    ui.ok(f"freeze {data['name']}  IS_DST={'yes' if dst else 'no'}")
    if not dst:
        ui.warn("DST needs both op-oc and run-oc session ids")
    print_inspect(data)
    hub.push_best_effort()


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
        raise SystemExit("[err] DST not ready. dt enter --oc / dt work --oc, then dt freeze")
    ui.ok(f"DST {data['name']}")
    print_inspect(data)
    hub.push_best_effort()


def cmd_resume(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    opsdir.prepare(data)
    if not oc_ops.is_dst(data):
        raise SystemExit("[err] not a DST. Freeze both oc sessions first: dt freeze")
    jump = (data.get("runtime") or {}).get("cmd") or ""
    if jump and tmux_ops.pane_command(data["run"]) not in {"ssh", "docker", "tmux", "opencode"}:
        tmux_ops.reconnect(data["run"], jump)
    _start_side(data, data["op"], "trigger", "", True)
    _start_side(data, data["run"], "bullet", "", True)
    wp.stamp(data, "resume_at")
    data["op_point"] = wp.discover(data["op"])
    data["run_point"] = wp.discover(data["run"])
    save(find_dt(data["name"]), data)
    ev.emit("dt.resume", name=data["name"])
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
            "usage: dt config --init --client tm_<id> --server <ssh-host> --user <name>"
        )
    print("First-time setup. dual-tmux does not write SSH keys or ~/.ssh/config.")
    print(f"client: {SOURCE_HINT}")
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
    client = _prompt("client (tm_*): ")
    server = _prompt("server (alias or ssh ...): ")
    user = _prompt("user: ")
    path = init_config(client, server, user, workspace or "/workspace")
    cfg = load_config()
    ui.ok(f"wrote {path}")
    ui.info(f"client={cfg.client}  server={cfg.server}  user={cfg.user}")
    if cfg.ssh_port != 22:
        ui.info(f"ssh_port={cfg.ssh_port}  (not written to ~/.ssh)")
    ui.info(f"remote persist {remote_sessions_root(cfg.user)}")
    hint = f"ssh -p {cfg.ssh_port} {cfg.server}" if cfg.ssh_port != 22 else f"ssh {cfg.server}"
    ui.print_next_init()
    ui.info(f"then: {hint} && dt doctor")


def cmd_config(args: argparse.Namespace) -> None:
    if args.init:
        if not args.client or not args.server or not args.user:
            prompt_init(args.workspace)
            return
        path = init_config(args.client, args.server, args.user, args.workspace)
        cfg = load_config()
        ui.ok(f"wrote {path}")
        ui.info(f"client={cfg.client}  server={cfg.server}  user={cfg.user}")
        if cfg.ssh_port != 22:
            ui.info(f"ssh_port={cfg.ssh_port}  (not written to ~/.ssh)")
        ui.info(f"remote persist {remote_sessions_root(cfg.user)}")
        hint = f"ssh -p {cfg.ssh_port} {cfg.server}" if cfg.ssh_port != 22 else f"ssh {cfg.server}"
        ui.info(f"next: {hint} && dt doctor")
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
    ui.info(f"server     {cfg.server}")
    if cfg.ssh_port != 22:
        ui.info(f"ssh_port   {cfg.ssh_port}")
    ui.info(f"user       {cfg.user}")
    ui.info(f"remote     {remote_sessions_root(cfg.user)}")
    ui.info(f"hub        {remote_dt_root(cfg.user)}")
    ui.info(f"workspace  {cfg.workspace}")
    if args.client or args.server or args.user or args.workspace != "/workspace":
        path = init_config(
            args.client or cfg.client,
            args.server or cfg.server,
            args.user or cfg.user,
            args.workspace if args.workspace != "/workspace" else cfg.workspace,
        )
        ui.ok(f"updated {path}")


def cmd_doctor(_: argparse.Namespace) -> None:
    _, checks = collect_checks()
    ok = print_checks(checks)
    ui.info(f"tunnels  {len(iter_dt_files())}")
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
        answer = input(f"rm {name}  op={op}  run={run}  kill_tmux={args.kill}? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            ui.skip("cancelled")
            return
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
    ui.ok(f"pushed tunnels+entries → {dest}")
    ui.info("config.toml / ops / events stay on this Client")


def cmd_pull(_: argparse.Namespace) -> None:
    dest = hub.pull()
    ui.ok(f"pulled tunnels+entries ← {dest}")
    ui.info(f"this Client stays {require_config().client}")


def cmd_log(args: argparse.Namespace) -> None:
    rows = ev.read_events(limit=args.limit, kind=args.kind, name=args.name or "")
    ui.print_log(rows)


def cmd_upgrade(_: argparse.Namespace) -> None:
    ui.info(f"Current version: {__version__}")
    result = subprocess.run(
        ["uv", "tool", "upgrade", "dual-tmux"],
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


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
    p_ins = sub.add_parser("inspect", help="show DT/DST fields including empty tool/model/session")
    p_ins.add_argument("name", nargs="?", help="defaults to latest tunnel")

    p_rm = sub.add_parser("rm", help="unregister a DT; --kill also destroys op_*/run_* tmux")
    p_rm.add_argument("name")
    p_rm.add_argument("--yes", "-y", action="store_true", help="do not prompt")
    p_rm.add_argument("--kill", action="store_true", help="tmux kill-session op_* and run_*")

    p_new = sub.add_parser("new", help="create op/run sessions and register a tunnel")
    p_new.add_argument("name", help="dt-app or app")
    p_new.add_argument("--op", help="defaults to op_<name>")
    p_new.add_argument("--run", help="defaults to run_<name>")
    p_new.add_argument("--server", default="", help="overrides config server (ssh host)")
    p_new.add_argument("--container", default="")
    p_new.add_argument("--dir", default="", help="remote working directory")
    p_new.add_argument("--cmd", default="", help="override reconnect command")

    p_bind = sub.add_parser("bind", help="set DST tool/model/session_id on trigger and bullet")
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
            p.add_argument("--oc", action="store_true", help="start OpenCode in that tmux")
            p.add_argument("--model", default="", help="model for --oc")
            p.add_argument("--resume", action="store_true", help="resume by recorded session_id")

    p_freeze = sub.add_parser("freeze", help="freeze op-oc and run-oc; DST only if both exist")
    p_freeze.add_argument("name", nargs="?", help="defaults to latest tunnel")
    p_freeze.add_argument("--trigger", action="store_true")
    p_freeze.add_argument("--bullet", action="store_true")
    p_freeze.add_argument("--tool", default="opencode")
    p_cap = sub.add_parser("capture", help="alias of freeze")
    p_cap.add_argument("name", nargs="?", help="defaults to latest tunnel")
    p_cap.add_argument("--trigger", action="store_true")
    p_cap.add_argument("--bullet", action="store_true")
    p_cap.add_argument("--tool", default="opencode")

    p_make = sub.add_parser("make", help="dt make dst <name> — create DT + both oc and freeze")
    p_make.add_argument("target", choices=["dst"])
    p_make.add_argument("name")
    p_make.add_argument("--tool", default="opencode")
    p_make.add_argument("--model", default="", help="model for both sides")
    p_make.add_argument("--trigger-model", default="")
    p_make.add_argument("--bullet-model", default="")
    p_make.add_argument("--container", default="")
    p_make.add_argument("--dir", default="")

    p_resume = sub.add_parser("resume", help="resume a DST; reconnects missing op/run oc")
    p_resume.add_argument("name", nargs="?", help="defaults to latest tunnel")

    p_send = sub.add_parser("send", help="send-keys into run_*")
    p_send.add_argument("name")
    p_send.add_argument("text")

    p_config = sub.add_parser("config", help="show or init Client/Server config")
    p_config.add_argument("--init", action="store_true")
    p_config.add_argument("--client", default="", help="legal local source name, must start with tm_")
    p_config.add_argument("--server", default="", help="ssh Host alias already in ~/.ssh/config")
    p_config.add_argument("--user", default="", help="person id; remote persist ~/<user>/sessions")
    p_config.add_argument("--workspace", default="/workspace")

    sub.add_parser("push", help="rsync tunnels+entries to Server ~/<user>/dual-tmux")
    sub.add_parser("pull", help="rsync tunnels+entries from Server; keeps this Client config.toml")

    p_log = sub.add_parser("log", help="show CLI event log (~/.dual-tmux/events.jsonl)")
    p_log.add_argument("-n", "--limit", type=int, default=40)
    p_log.add_argument("--kind", default="", help="prefix filter, e.g. freeze")
    p_log.add_argument("--name", default="", help="filter by DT name")

    sub.add_parser("doctor", help="check config, tmux, ssh")
    sub.add_parser("upgrade", help="upgrade via uv tool")
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
    if command not in {"config", "doctor", "upgrade", "ls", "show", "inspect", "log"}:
        if not config_path().is_file():
            prompt_init()
        ensure_ready()
    handlers = {
        "ls": cmd_ls,
        "show": cmd_show,
        "inspect": cmd_inspect,
        "new": cmd_new,
        "rm": cmd_rm,
        "bind": cmd_bind,
        "freeze": cmd_freeze,
        "capture": cmd_capture,
        "make": cmd_make,
        "resume": cmd_resume,
        "enter": cmd_enter,
        "work": cmd_work,
        "re": cmd_re,
        "send": cmd_send,
        "config": cmd_config,
        "push": cmd_push,
        "pull": cmd_pull,
        "log": cmd_log,
        "doctor": cmd_doctor,
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
