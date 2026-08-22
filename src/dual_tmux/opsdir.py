from __future__ import annotations

import shutil
from pathlib import Path

from .paths import home_dir, tunnels_dir


def packaged_skills() -> Path:
    return Path(__file__).resolve().parent / "skills"


def skills_dir() -> Path:
    return home_dir() / "skills"


def ops_dir(op: str) -> Path:
    return home_dir() / "ops" / op


def sync_skills() -> Path:
    src = packaged_skills()
    dest = skills_dir()
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    return dest


def install_project_skills(dest: Path) -> Path:
    """OpenCode only discovers .opencode/skills/<name>/SKILL.md from cwd."""
    src = packaged_skills()
    target = dest / ".opencode" / "skills"
    target.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, target, dirs_exist_ok=True)
    return target


def write_opencode_json(dest: Path) -> Path:
    """AGENTS.md does not auto-load linked files; instructions does."""
    path = dest / "opencode.json"
    path.write_text(
        "{\n"
        '  "$schema": "https://opencode.ai/config.json",\n'
        '  "instructions": [\n'
        '    ".opencode/skills/dual-tmux/SKILL.md",\n'
        '    ".opencode/skills/tmux-trigger/SKILL.md"\n'
        "  ]\n"
        "}\n"
    )
    return path


def agents_text(data: dict) -> str:
    name = data.get("name") or ""
    op = data.get("op") or ""
    run = data.get("run") or ""
    trigger = data.get("trigger") or {}
    bullet = data.get("bullet") or {}
    runtime = data.get("runtime") or {}
    skills = skills_dir()
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
        "- `.opencode/skills/dual-tmux/SKILL.md`\n"
        "- `.opencode/skills/tmux-trigger/SKILL.md`\n"
        "\n"
        "Treat them as mandatory. Same files are also listed in `opencode.json` `instructions`.\n"
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
    install_project_skills(dest)
    write_opencode_json(dest)
    (dest / "AGENTS.md").write_text(agents_text(data), encoding="utf-8")
    mem.prepare_for_tunnel(data)
    return dest


def remove_ops(op: str) -> None:
    dest = ops_dir(op)
    if dest.is_dir():
        shutil.rmtree(dest, ignore_errors=True)
