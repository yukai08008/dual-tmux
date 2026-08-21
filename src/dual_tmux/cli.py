from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .identity import init_name, name_file, require_me
from .runtime import build_cmd
from .store import (
    default_names,
    dt_dir,
    find_dt,
    iter_dt_files,
    latest_dt,
    legal_op,
    legal_run,
    load,
    normalize_dt,
    occupied,
    save,
    write_entry,
    now_iso,
)
from . import tmux as tmux_ops


def cmd_version(_: argparse.Namespace) -> None:
    if sys.stdout.isatty():
        print(f"dual-tmux {__version__}")
        print(f"Python    {sys.version.split()[0]}")
        print(f"System    {platform.system()} {platform.release()} ({platform.machine()})")
    else:
        print(f"dt {__version__}")


def cmd_ls(_: argparse.Namespace) -> None:
    files = iter_dt_files()
    if not files:
        print("(无 dt 登记)")
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
    me = require_me()
    name, default_op, default_run = default_names(args.name)
    op = args.op or default_op
    run = args.run or default_run
    if not legal_op(op):
        raise SystemExit("[err] --op 必须 op_ 开头")
    if not legal_run(run):
        raise SystemExit("[err] --run 必须 run_ 开头")
    other = occupied("op", op, skip=name)
    if other:
        raise SystemExit(f"[err] {op} 已被 {other} 占用")
    other = occupied("run", run, skip=name)
    if other:
        raise SystemExit(f"[err] {run} 已被 {other} 占用")
    cmd = args.cmd or build_cmd(args.host, args.container or "", args.dir)
    tmux_ops.ensure_session(op)
    tmux_ops.ensure_session(run)
    write_entry(me, run, cmd)
    data = {
        "name": name,
        "op": op,
        "run": run,
        "runtime": {
            "host": args.host,
            "container": args.container or "",
            "directory": args.dir,
            "cmd": cmd,
        },
        "trigger": {"slug": "", "session_id": ""},
        "bullet": {"slug": "", "session_id": ""},
        "holder": me,
        "updated_at": now_iso(),
    }
    path = dt_dir(me) / f"{name}.json"
    if path.exists():
        old = load(path)
        data["trigger"] = old.get("trigger") or data["trigger"]
        data["bullet"] = old.get("bullet") or data["bullet"]
    save(path, data)
    print(f"[ok] 已登记 {name}")
    print(f"     op={op}  run={run}")
    print(f"     cmd={cmd}")
    print(f"     进线头: dt enter {name}")
    print(f"     进现场: dt work {name}")


def cmd_bind(args: argparse.Namespace) -> None:
    me = require_me()
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
    data["holder"] = me
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
        raise SystemExit("[err] 隧道没有 runtime.cmd")
    tmux_ops.reconnect(data["run"], cmd)


def cmd_send(args: argparse.Namespace) -> None:
    data = _resolve(args.name)
    tmux_ops.send_keys(data["run"], args.text)


def cmd_config(args: argparse.Namespace) -> None:
    if args.init:
        name = args.name or os.environ.get("SYNC_NAME") or ""
        if not name:
            raise SystemExit("用法: dt config --init tm_andy_ouc")
        path = init_name(name)
        print(f"[ok] 来源名 {name} -> {path}")
        return
    path = name_file()
    if path.is_file():
        print(f"name file  {path}")
        print(f"name       {path.read_text().strip()}")
    else:
        print(f"name file  {path} (missing)")
        print("fix: dt config --init tm_andy_ouc")


def cmd_doctor(_: argparse.Namespace) -> None:
    ok = True

    def check(label: str, good: bool, detail: str) -> None:
        nonlocal ok
        mark = "OK " if good else "ERR"
        if not good:
            ok = False
        print(f"{mark}  {label:<14} {detail}")

    try:
        me = require_me()
        check("source name", True, me)
    except SystemExit as exc:
        check("source name", False, str(exc).removeprefix("[err] "))
        me = ""
    check("tmux", tmux_ops.have_tmux(), shutil.which("tmux") or "not in PATH")
    check("ssh", shutil.which("ssh") is not None, shutil.which("ssh") or "not in PATH")
    host = os.environ.get("DT_SSH_HOST", "tom7r")
    ssh = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "echo ok"],
        capture_output=True,
        text=True,
    )
    check(f"ssh {host}", ssh.returncode == 0, (ssh.stdout or ssh.stderr or "").strip()[:80] or "failed")
    persist = Path.home() / "crons" / "tmux" / "rsync_to_tom7r"
    check("persist cron", persist.exists() or persist.is_symlink(), str(persist))
    tunnels = len(iter_dt_files())
    check("tunnels", True, str(tunnels))
    if not ok:
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
        description="Dual tmux tunnels: op_* line head + run_* jump host, 1:1 dt-* binding",
    )
    parser.add_argument("--version", action="store_true", help="show version")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("ls", help="list tunnels")
    p_show = sub.add_parser("show", help="show one tunnel JSON")
    p_show.add_argument("name")

    p_new = sub.add_parser("new", help="create op/run sessions and register a tunnel")
    p_new.add_argument("name", help="dt-cp-gateway or cp-gateway")
    p_new.add_argument("--op", help="defaults to op_<name>")
    p_new.add_argument("--run", help="defaults to run_<name>")
    p_new.add_argument("--host", default="tom7r")
    p_new.add_argument("--container", default="")
    p_new.add_argument("--dir", default="/workspace")
    p_new.add_argument("--cmd", default="", help="override reconnect command")

    p_bind = sub.add_parser("bind", help="bind trigger/bullet opencode sessions")
    p_bind.add_argument("name")
    p_bind.add_argument("--trigger", default="")
    p_bind.add_argument("--bullet", default="")
    p_bind.add_argument("--trigger-id", default="")
    p_bind.add_argument("--bullet-id", default="")

    for name, help_text in (
        ("enter", "attach op_* (line head)"),
        ("work", "attach run_* (workspace jump)"),
        ("re", "re-send runtime ssh/docker into run_*"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("name", nargs="?", help="defaults to latest tunnel")

    p_send = sub.add_parser("send", help="send-keys into run_* (trigger dispatch)")
    p_send.add_argument("name")
    p_send.add_argument("text")

    p_config = sub.add_parser("config", help="show or init source name")
    p_config.add_argument("--init", action="store_true")
    p_config.add_argument("name", nargs="?", help="tm_andy_ouc")

    sub.add_parser("doctor", help="check tm_, tmux, ssh, persist")
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
        cmd_enter(argparse.Namespace(name=None))
        return
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
