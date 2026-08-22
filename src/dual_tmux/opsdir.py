from __future__ import annotations

import shutil
from pathlib import Path

from .paths import home_dir, tunnels_dir
from . import skillmgr


def packaged_skills() -> Path:
    return skillmgr.packaged_skills()


def skills_dir() -> Path:
    return skillmgr.catalog_dir()


def ops_dir(op: str) -> Path:
    return home_dir() / "ops" / op


def sync_skills() -> Path:
    skillmgr.seed_catalog()
    return skillmgr.catalog_dir()


def install_project_skills(dest: Path, names: list[str] | None = None) -> Path:
    names = names if names is not None else skillmgr.enabled("trigger")
    return skillmgr.install_into(dest, names)


def write_opencode_json(dest: Path, names: list[str] | None = None) -> Path:
    names = names if names is not None else skillmgr.enabled("trigger")
    return skillmgr.write_opencode_json(dest, names)


def agents_text(data: dict) -> str:
    name = data.get("name") or ""
    op = data.get("op") or ""
    run = data.get("run") or ""
    trigger = data.get("trigger") or {}
    bullet = data.get("bullet") or {}
    runtime = data.get("runtime") or {}
    names = skillmgr.enabled("trigger")
    skill_lines = "\n".join(f"- `.opencode/skills/{n}/SKILL.md`" for n in names)
    return (
        f"# Trigger for {name}\n"
        "\n"
        f"You are the **trigger** OpenCode in tmux `{op}` on this Client.\n"
        f"Bullet is tmux `{run}`. Dispatch with `tmux send-keys -t {run}`, then poll.\n"
        "Do not ssh / docker exec the coding task yourself.\n"
        "If bullet asks to rebuild/replace the workspace container, you do that on the "
        "host (outside the container), then `dt re`. Bullet must not recreate the box it runs in.\n"
        "Architecture and flow: dispatch to bullet; require mermaid filed in the workspace, not chat-only.\n"
        "\n"
        "## Read first\n"
        "\n"
        "CRITICAL: On startup, immediately Read these files with your Read tool "
        "(OpenCode does not auto-follow links in AGENTS.md):\n"
        "\n"
        f"{skill_lines}\n"
        "\n"
        "Treat them as mandatory. Same files are also listed in `opencode.json` `instructions`.\n"
        "Catalog (all skills): `~/.dual-tmux/skills/`. Trigger uses the subset in `dt skill`.\n"
        "After using a skill: `dt skill used <dt> <skill> --ok|--fail`.\n"
        "Teach bullet: `dt skill teach <dt> <skill>`.\n"
        "\n"
        "## This tunnel\n"
        "\n"
        f"- DT: `{name}`\n"
        f"- op / trigger tmux: `{op}`\n"
        f"- run / bullet tmux: `{run}`\n"
        f"- server: `{runtime.get('server') or '—'}`\n"
        f"- container: `{runtime.get('container') or '—'}`\n"
        f"- trigger session: `{trigger.get('session_id') or '—'}` model `{trigger.get('model') or '—'}`\n"
        f"- bullet session: `{bullet.get('session_id') or '—'}` model `{bullet.get('model') or '—'}`\n"
        f"- tunnel JSON: `{tunnels_dir() / f'{name}.json'}`\n"
        "\n"
        "## Memory\n"
        "\n"
        f"- shared facts: `{home_dir() / 'MEMORY.json'}`  (`dt mem`)\n"
        f"- this agent facts: `{ops_dir(op) / 'MEMORY.json'}`  (`dt mem {name}`)\n"
        f"- this agent log: `{ops_dir(op) / 'memory.sqlite'}`  (`dt note {name} …` / `dt notes {name}`)\n"
        "\n"
        "Resume either side with `opencode --auto -s <id>`, never `-c`.\n"
        f"Re-jump: `dt re {name}`\n"
    )


def prepare(data: dict) -> Path:
    from . import memory as mem

    sync_skills()
    dest = ops_dir(data["op"])
    dest.mkdir(parents=True, exist_ok=True)
    names = skillmgr.enabled("trigger")
    install_project_skills(dest, names)
    write_opencode_json(dest, names)
    (dest / "AGENTS.md").write_text(agents_text(data), encoding="utf-8")
    mem.prepare_for_tunnel(data)
    return dest


def remove_ops(op: str) -> None:
    dest = ops_dir(op)
    if dest.is_dir():
        shutil.rmtree(dest, ignore_errors=True)
