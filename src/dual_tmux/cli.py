from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys

from . import __version__
from .config import AppConfig, init_config, load_config
from . import oc as oc_ops
from .identity import SOURCE_HINT, USER_HINT, remote_sessions_root
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
)
from . import tmux as tmux_ops


def require_config() -> AppConfig:
    return load_config()


def cmd_version(_: argparse.Namespace) -> None:
    if sys.stdout.isatty():
        print(f"dual-tmux {__version__}")
        print(f"Python    {sys.version.split()[0]}")
        print(f"System    {platform.system()} {platform.release()} ({platform.machine()})")
        print(f"Home      {home_dir()}")
    else:
        print(f"dt {__version__}")


def cmd_ls(_: argparse.Namespace) -> None:
    files = iter_dt_files()
    if not files:
        print("(no tunnels)")
        return
    print(f"{'DST':<24} {'OP':<18} {'RUN':<18} TRIGGER              BULLET")
    for path in files:
        data = load(path)
        trigger = _oc_label(data.get("trigger") or {})
        bullet = _oc_label(data.get("bullet") or {})
        print(
            f"{data.get('name','?'):<24} {data.get('op','?'):<18} "
            f"{data.get('run','?'):<18} {trigger:<20} {bullet}"
        )


def cmd_show(args: argparse.Namespace) -> None:
    path = find_dt(args.name)
    print(json.dumps(load(path), ensure_ascii=False, indent=2))


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
    tmux_ops.ensure_session(op)
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
        "updated_at": now_iso(),
    }
    path = tunnels_dir() / f"{name}.json"
    if path.exists():
        old = load(path)
        data["trigger"] = old.get("trigger") or data["trigger"]
        data["bullet"] = old.get("bullet") or data["bullet"]
    save(path, data)
    print(f"[ok] registered {name}")
    print(f"     op={op}  run={run}")
    print(f"     server={server}  cmd={cmd}")
    print(f"     enter: dt enter {name}")
    print(f"     work:  dt work {name}")


def _oc_label(info: dict) -> str:
    tool = info.get("tool") or "opencode"
    model = info.get("model") or "-"
    sid = info.get("session_id") or ""
    short = sid[:10] if sid else "-"
    return f"{tool}:{model}:{short}"


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
    print(
        f"     {label:<8} tool={info.get('tool') or '-'}  "
        f"model={info.get('model') or '-'}  "
        f"session={info.get('session_id') or '-'}"
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
    print(f"[ok] dst {data['name']}")
    _print_side("trigger", trigger)
    _print_side("bullet", bullet)


def _resolve(name: str | None) -> dict:
    path = find_dt(name) if name else latest_dt()
    return load(path)


def print_next_after_init() -> None:
    print()
    print("Config is ready. Next:")
    print("  dt doctor              # check tmux + ssh")
    print("  dt new <name>          # create the first tunnel (op_* + run_*)")
    print("  dt                     # attach latest op_* once a tunnel exists")


def cmd_enter(args: argparse.Namespace) -> None:
    if not args.name and not iter_dt_files():
        print_next_after_init()
        return
    data = _resolve(args.name)
    if getattr(args, "oc", False) or getattr(args, "resume", False):
        info = _side(data, "trigger")
        resume = getattr(args, "resume", False) or bool(info.get("session_id"))
        cmd = oc_ops.resume_cmd(info) if resume else "opencode"
        tmux_ops.start_opencode(data["op"], cmd if cmd != "opencode" else "")
        if info.get("session_id"):
            print(f"[ok] resume trigger {info.get('tool')} {info.get('model')} {info.get('session_id')}")
        else:
            print(f"[ok] start trigger opencode in {data['op']}. Then: dt capture {data['name']} --trigger")
    tmux_ops.attach(data["op"])


def cmd_work(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    if getattr(args, "oc", False) or getattr(args, "resume", False):
        info = _side(data, "bullet")
        resume = getattr(args, "resume", False) or bool(info.get("session_id"))
        cmd = oc_ops.resume_cmd(info) if resume else "opencode"
        tmux_ops.start_opencode(data["run"], cmd if cmd != "opencode" else "")
        if info.get("session_id"):
            print(f"[ok] resume bullet {info.get('tool')} {info.get('model')} {info.get('session_id')}")
        else:
            print(f"[ok] start bullet opencode in {data['run']}. Then: dt capture {data['name']} --bullet")
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


def cmd_capture(args: argparse.Namespace) -> None:
    path = find_dt(args.name) if args.name else latest_dt()
    data = load(path)
    cfg = require_config()
    runtime = data.get("runtime") or {}
    sides: list[str] = []
    if args.trigger or (not args.trigger and not args.bullet):
        sides.append("trigger")
    if args.bullet or (not args.trigger and not args.bullet):
        sides.append("bullet")
    if "trigger" in sides:
        latest = oc_ops.latest_local(1)
        if not latest:
            raise SystemExit("[err] no local opencode session. dt enter --oc, start oc, then capture")
        _bind_oc(data, "trigger", latest[0], getattr(args, "tool", "") or "opencode")
        _print_side("trigger", data["trigger"])
    if "bullet" in sides:
        from .sshutil import SshTarget

        server = runtime.get("server") or cfg.server
        port = int(runtime.get("ssh_port") or cfg.ssh_port or 22)
        target = SshTarget(server, port)
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", *target.extra_args, target.dest]
        session = oc_ops.latest_remote(argv, runtime.get("container") or "")
        if not session:
            raise SystemExit("[err] no remote opencode session. dt work --oc, start oc, then capture")
        _bind_oc(data, "bullet", session, getattr(args, "tool", "") or "opencode")
        _print_side("bullet", data["bullet"])
    save(path, data)


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
    print(f"[ok] wrote {path}")
    print(f"     client={cfg.client}  server={cfg.server}  user={cfg.user}")
    if cfg.ssh_port != 22:
        print(f"     ssh_port={cfg.ssh_port}  (not written to ~/.ssh)")
    print(f"     remote persist {remote_sessions_root(cfg.user)}")
    hint = f"ssh -p {cfg.ssh_port} {cfg.server}" if cfg.ssh_port != 22 else f"ssh {cfg.server}"
    print(f"     next: {hint} && dt doctor")


def cmd_config(args: argparse.Namespace) -> None:
    if args.init:
        if not args.client or not args.server or not args.user:
            prompt_init(args.workspace)
            return
        path = init_config(args.client, args.server, args.user, args.workspace)
        cfg = load_config()
        print(f"[ok] wrote {path}")
        print(f"     client={cfg.client}  server={cfg.server}  user={cfg.user}")
        if cfg.ssh_port != 22:
            print(f"     ssh_port={cfg.ssh_port}  (not written to ~/.ssh)")
        print(f"     remote persist {remote_sessions_root(cfg.user)}")
        print("     SSH is yours: this CLI never writes ~/.ssh or keys.")
        hint = f"ssh -p {cfg.ssh_port} {cfg.server}" if cfg.ssh_port != 22 else f"ssh {cfg.server}"
        print(f"     next: {hint} && dt doctor")
        return
    path = config_path()
    if not path.is_file():
        print(f"config     {path} (missing)")
        print("fix: dt config --init --client tm_laptop --server myserver --user ouc")
        return
    cfg = load_config()
    print(f"home       {home_dir()}")
    print(f"config     {path}")
    print(f"client     {cfg.client}")
    print(f"server     {cfg.server}")
    if cfg.ssh_port != 22:
        print(f"ssh_port   {cfg.ssh_port}")
    print(f"user       {cfg.user}")
    print(f"remote     {remote_sessions_root(cfg.user)}")
    print(f"workspace  {cfg.workspace}")
    if args.client or args.server or args.user or args.workspace != "/workspace":
        path = init_config(
            args.client or cfg.client,
            args.server or cfg.server,
            args.user or cfg.user,
            args.workspace if args.workspace != "/workspace" else cfg.workspace,
        )
        print(f"[ok] updated {path}")


def cmd_doctor(_: argparse.Namespace) -> None:
    _, checks = collect_checks()
    ok = print_checks(checks)
    print(f"{'OK ' if ok else '   '}  {'tunnels':<12} {len(iter_dt_files())}")
    if not ok:
        guide_if_needed(checks)
        raise SystemExit(1)


def cmd_upgrade(_: argparse.Namespace) -> None:
    print(f"Current version: {__version__}")
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

    sub.add_parser("ls", help="list tunnels")
    p_show = sub.add_parser("show", help="show one tunnel JSON")
    p_show.add_argument("name")

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
            p.add_argument("--oc", action="store_true", help="start or resume the bound agent in that tmux")
            p.add_argument("--resume", action="store_true", help="resume by recorded session_id")

    p_cap = sub.add_parser("capture", help="record tool/model/session_id from live OpenCode")
    p_cap.add_argument("name", nargs="?", help="defaults to latest tunnel")
    p_cap.add_argument("--trigger", action="store_true", help="capture local opencode as trigger")
    p_cap.add_argument("--bullet", action="store_true", help="capture remote opencode as bullet")
    p_cap.add_argument("--tool", default="opencode", help="agent tool name, default opencode")

    p_send = sub.add_parser("send", help="send-keys into run_*")
    p_send.add_argument("name")
    p_send.add_argument("text")

    p_config = sub.add_parser("config", help="show or init Client/Server config")
    p_config.add_argument("--init", action="store_true")
    p_config.add_argument("--client", default="", help="legal local source name, must start with tm_")
    p_config.add_argument("--server", default="", help="ssh Host alias already in ~/.ssh/config")
    p_config.add_argument("--user", default="", help="person id; remote persist ~/<user>/sessions")
    p_config.add_argument("--workspace", default="/workspace")

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
    if command not in {"config", "doctor", "upgrade", "ls", "show"}:
        if not config_path().is_file():
            prompt_init()
        ensure_ready()
    handlers = {
        "ls": cmd_ls,
        "show": cmd_show,
        "new": cmd_new,
        "bind": cmd_bind,
        "capture": cmd_capture,
        "enter": cmd_enter,
        "work": cmd_work,
        "re": cmd_re,
        "send": cmd_send,
        "config": cmd_config,
        "doctor": cmd_doctor,
        "upgrade": cmd_upgrade,
    }
    handlers[command](args)


if __name__ == "__main__":
    main()
