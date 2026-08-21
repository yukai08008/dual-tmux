from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from . import oc as oc_ops

console = Console(highlight=False)


def blank(value: str | None) -> str:
    return value if value else "—"


def dst_text(yes: bool) -> Text:
    if yes:
        return Text("yes", style="bold green")
    return Text("no", style="dim")


def ok(msg: str) -> None:
    console.print(f"[bold green]ok[/]  {msg}")


def skip(msg: str) -> None:
    console.print(f"[yellow]skip[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]![/] {msg}")


def err(msg: str) -> None:
    console.print(f"[bold red]err[/] {msg}")


def info(msg: str) -> None:
    console.print(f"[cyan]·[/] {msg}")


def print_version(version: str, python: str, system: str, home: str) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("dual-tmux", f"[bold]{version}[/]")
    table.add_row("Python", python)
    table.add_row("System", system)
    table.add_row("Home", home)
    console.print(Panel(table, title="dt", border_style="cyan", padding=(0, 1)))


def print_ls(rows: list[dict]) -> None:
    if not rows:
        console.print("[dim](no tunnels)[/]")
        return
    table = Table(title="tunnels", border_style="cyan", header_style="bold")
    table.add_column("DT")
    table.add_column("IS_DST")
    table.add_column("op")
    table.add_column("run")
    table.add_column("trigger")
    table.add_column("bullet")
    for data in rows:
        table.add_row(
            str(data.get("name") or "—"),
            dst_text(oc_ops.is_dst(data)),
            str(data.get("op") or "—"),
            str(data.get("run") or "—"),
            _side_cell(data.get("trigger") or {}),
            _side_cell(data.get("bullet") or {}),
        )
    console.print(table)


def _side_cell(info: dict) -> Text:
    tool = info.get("tool") or "opencode"
    model = info.get("model") or "—"
    sid = info.get("session_id") or ""
    short = sid[:10] if sid else "—"
    text = Text()
    text.append(tool, style="cyan")
    text.append(" ")
    text.append(model, style="magenta" if info.get("model") else "dim")
    text.append(" ")
    text.append(short, style="green" if sid else "dim")
    return text


def print_inspect(data: dict) -> None:
    runtime = data.get("runtime") or {}
    trigger = data.get("trigger") or oc_ops.empty_side()
    bullet = data.get("bullet") or oc_ops.empty_side()
    dst = oc_ops.is_dst(data)
    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="dim", min_width=8)
    meta.add_column()
    meta.add_row("DT", f"[bold]{data.get('name', '—')}[/]")
    meta.add_row("IS_DST", dst_text(dst))
    meta.add_row("op", str(data.get("op") or "—"))
    meta.add_row("run", str(data.get("run") or "—"))
    meta.add_row("server", blank(runtime.get("server")))
    meta.add_row("cmd", f"[dim]{blank(runtime.get('cmd'))}[/]")
    op_point = data.get("op_point") or {}
    run_point = data.get("run_point") or {}
    meta.add_row("op point", f"{blank(op_point.get('kind'))}  cwd={blank(op_point.get('cwd'))}")
    meta.add_row("run point", f"{blank(run_point.get('kind'))}  cwd={blank(run_point.get('cwd'))}  ssh={blank(run_point.get('ssh'))}  docker={blank(run_point.get('container'))}")
    times = data.get("times") or {}
    if any(times.values()):
        meta.add_row("created", blank(times.get("created_at")))
        meta.add_row("enter", blank(times.get("enter_at")))
        meta.add_row("work", blank(times.get("work_at")))
        meta.add_row("freeze", blank(times.get("freeze_at")))
    sides = Table(border_style="dim", header_style="bold", expand=True)
    sides.add_column("")
    sides.add_column("tool")
    sides.add_column("model")
    sides.add_column("session")
    sides.add_column("slug")
    sides.add_row(
        "[cyan]op / trigger[/]",
        blank(trigger.get("tool")),
        blank(trigger.get("model")),
        blank(trigger.get("session_id")),
        blank(trigger.get("slug")),
    )
    sides.add_row(
        "[magenta]run / bullet[/]",
        blank(bullet.get("tool")),
        blank(bullet.get("model")),
        blank(bullet.get("session_id")),
        blank(bullet.get("slug")),
    )
    console.print(Panel(meta, title="inspect", border_style="green" if dst else "cyan", padding=(0, 1)))
    console.print(sides)


def print_checks(checks) -> bool:
    table = Table(title="doctor", border_style="cyan", header_style="bold")
    table.add_column("status", width=6)
    table.add_column("check")
    table.add_column("detail")
    ok_all = True
    for item in checks:
        if item.ok:
            status = Text("OK", style="bold green")
        else:
            status = Text("ERR", style="bold red")
            ok_all = False
        detail = Text(item.detail)
        if not item.ok and item.hint:
            detail.append(f"\n{item.hint}", style="dim yellow")
        table.add_row(status, item.label, detail)
    console.print(table)
    return ok_all


def print_guide() -> None:
    console.print(
        Panel(
            "[bold]Client → Server is not ready.[/]\n"
            "Fill three fields. This CLI never writes [cyan]~/.ssh[/] or keys.\n\n"
            "  [bold]client[/]  legal local source name ([cyan]tm_*[/])\n"
            "  [bold]server[/]  ssh Host alias already in ~/.ssh/config\n"
            "  [bold]user[/]    person id; remote persist [cyan]~/<user>/sessions[/]\n\n"
            "  dt config --init --client tm_<id> --server <ssh-host> --user <name>\n"
            "  ssh <ssh-host>\n"
            "  dt doctor",
            title="setup",
            border_style="yellow",
        )
    )


def print_next_init() -> None:
    console.print(
        Panel(
            "[bold]Config is ready.[/]\n"
            "  dt doctor           check tmux + ssh\n"
            "  dt new [cyan]<name>[/]      create DT (op_* + run_*)\n"
            "  dt make dst [cyan]<name>[/] one-shot DST",
            title="next",
            border_style="cyan",
        )
    )


def print_next_new(name: str) -> None:
    console.print(
        Panel(
            f"dt enter {name} --oc [--model M]\n"
            f"dt work  {name} --oc [--model M]\n"
            f"dt freeze {name}\n"
            f"[dim]or[/] dt make dst {name}",
            title="next",
            border_style="cyan",
        )
    )
