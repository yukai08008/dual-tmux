from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys

from . import __version__
from .config import AppConfig, init_config, load_config, write_config
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
    print(f"{'NAME':<24} {'OP':<22} {'RUN':<22} TRIGGER          BULLET")
    for path in files:
        data = load(path)
        trigger = (data.get("trigger") or {}).get("slug") or "-"
        bullet = (data.get("bullet") or {}).get("slug") or "-"
        print(
            f"{data.get('name','?'):<24} {data.get('op','?'):<22} "
            f"{data.get('run','?'):<22} {trigger:<16} {bullet}"
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
    server = args.server or cfg.server
    directory = args.dir or cfg.workspace
    cmd = args.cmd or build_cmd(server, args.container or "", directory)
    tmux_ops.ensure_session(op)
    tmux_ops.ensure_session(run)
    write_entry(run, cmd)
    data = {
        "name": name,
        "op": op,
        "run": run,
        "client": cfg.client,
        "runtime": {
            "server": server,
            "container": args.container or "",
            "directory": directory,
            "cmd": cmd,
        },
        "trigger": {"slug": "", "session_id": ""},
        "bullet": {"slug": "", "session_id": ""},
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


def cmd_bind(args: argparse.Namespace) -> None:
    require_config()
    path = find_dt(args.name)
    data = load(path)
    trigger = data.setdefault("trigger", {"slug": "", "session_id": ""})
    bullet = data.setdefault("bullet", {"slug": "", "session_id": ""})
    if args.trigger:
        trigger["slug"] = args.trigger
    if args.trigger_id:
        trigger["session_id"] = args.trigger_id
    if args.bullet:
        bullet["slug"] = args.bullet
    if args.bullet_id:
        bullet["session_id"] = args.bullet_id
    data["updated_at"] = now_iso()
    save(path, data)
    print(
        f"[ok] {data['name']}  trigger={trigger.get('slug') or '-'}  "
        f"bullet={bullet.get('slug') or '-'}"
    )


def _resolve(name: str | None) -> dict:
    path = find_dt(name) if name else latest_dt()
    return load(path)


def cmd_enter(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    tmux_ops.attach(data["op"])


def cmd_work(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
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


def cmd_config(args: argparse.Namespace) -> None:
    if args.init:
        if not args.client or not args.server:
            raise SystemExit("usage: dt config --init --client <id> --server <ssh-host>")
        path = init_config(args.client, args.server, args.workspace)
        print(f"[ok] wrote {path}")
        print(f"     client={args.client}  server={args.server}")
        print("     SSH is yours: this CLI never writes ~/.ssh or keys.")
        print(f"     next: ssh {args.server} && dt doctor")
        return
    path = config_path()
    if not path.is_file():
        print(f"config     {path} (missing)")
        print("fix: dt config --init --client laptop --server myserver")
        return
    cfg = load_config()
    print(f"home       {home_dir()}")
    print(f"config     {path}")
    print(f"client     {cfg.client}")
    print(f"server     {cfg.server}")
    print(f"workspace  {cfg.workspace}")
    if args.client or args.server or args.workspace != "/workspace":
        cfg = AppConfig(
            client=args.client or cfg.client,
            server=args.server or cfg.server,
            workspace=args.workspace if args.workspace != "/workspace" else cfg.workspace,
        )
        write_config(cfg)
        print("[ok] updated")


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
        description="Dual tmux tunnels: Client op_* + Server jump run_*, 1:1 dt-* binding",
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

    p_bind = sub.add_parser("bind", help="bind trigger/bullet agent sessions")
    p_bind.add_argument("name")
    p_bind.add_argument("--trigger", default="")
    p_bind.add_argument("--bullet", default="")
    p_bind.add_argument("--trigger-id", default="")
    p_bind.add_argument("--bullet-id", default="")

    for name, help_text in (
        ("enter", "attach op_* (line head on Client)"),
        ("work", "attach run_* (jump to Server workspace)"),
        ("re", "re-send runtime ssh/docker into run_*"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("name", nargs="?", help="defaults to latest tunnel")

    p_send = sub.add_parser("send", help="send-keys into run_*")
    p_send.add_argument("name")
    p_send.add_argument("text")

    p_config = sub.add_parser("config", help="show or init Client/Server config")
    p_config.add_argument("--init", action="store_true")
    p_config.add_argument("--client", default="", help="this machine id")
    p_config.add_argument("--server", default="", help="ssh host alias of the Server")
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
        ensure_ready()
        cmd_enter(argparse.Namespace(name=None))
        return
    if command not in {"config", "doctor", "upgrade", "ls", "show"}:
        ensure_ready()
    handlers = {
        "ls": cmd_ls,
        "show": cmd_show,
        "new": cmd_new,
        "bind": cmd_bind,
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
