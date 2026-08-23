from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .paths import home_dir, skills_dir
from .store import find_dt, load, now_iso, save

CORE = ("dual-tmux", "tmux-trigger")
FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def catalog_dir() -> Path:
    return skills_dir()


def config_path() -> Path:
    return home_dir() / "skills.json"


def log_path() -> Path:
    return home_dir() / "skill-usage.jsonl"


def packaged_skills() -> Path:
    return Path(__file__).resolve().parent / "skills"


def default_config() -> dict:
    return {"trigger": list(CORE), "bullet": []}


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return default_config()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return default_config()
    trig = data.get("trigger")
    bull = data.get("bullet")
    if not isinstance(trig, list) or not trig:
        trig = list(CORE)
    if not isinstance(bull, list):
        bull = []
    return {"trigger": [str(x) for x in trig], "bullet": [str(x) for x in bull]}


def save_config(cfg: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    return path


def parse_frontmatter(text: str) -> dict:
    m = FRONT.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip("\"'")
    return out


def seed_catalog() -> list[str]:
    dest = catalog_dir()
    dest.mkdir(parents=True, exist_ok=True)
    added: list[str] = []
    src = packaged_skills()
    if not src.is_dir():
        return added
    for item in src.iterdir():
        if not item.is_dir() or not (item / "SKILL.md").is_file():
            continue
        target = dest / item.name
        if not target.exists():
            shutil.copytree(item, target)
            added.append(item.name)
            continue
        shutil.copytree(item, target, dirs_exist_ok=True)
        if item.name not in added:
            added.append(item.name)
    cfg = load_config()
    for name in CORE:
        if name not in cfg["trigger"]:
            cfg["trigger"].insert(0, name)
    save_config(cfg)
    return added


def list_catalog() -> list[dict]:
    seed_catalog()
    cfg = load_config()
    trig = set(cfg["trigger"])
    bull = set(cfg["bullet"])
    rows: list[dict] = []
    root = catalog_dir()
    if not root.is_dir():
        return rows
    for item in sorted(root.iterdir(), key=lambda p: p.name):
        skill = item / "SKILL.md"
        if not item.is_dir() or not skill.is_file():
            continue
        meta = parse_frontmatter(skill.read_text())
        name = meta.get("name") or item.name
        rows.append(
            {
                "name": name,
                "description": meta.get("description") or "",
                "trigger": name in trig,
                "bullet": name in bull,
                "path": str(skill),
            }
        )
    return rows


def _find_skill_md(root: Path) -> Path | None:
    direct = root / "SKILL.md"
    if direct.is_file():
        return direct
    hits = list(root.rglob("SKILL.md"))
    if len(hits) == 1:
        return hits[0]
    return None


def preview_source(src: str) -> dict:
    """Inspect folder / SKILL.md / zip without importing."""
    path = Path(src).expanduser().resolve()
    kind = "unknown"
    md = None
    files: list[str] = []
    tmp = None
    try:
        if path.is_file() and path.suffix.lower() == ".zip":
            kind = "zip"
            tmp = Path(tempfile.mkdtemp(prefix="dt-skill-"))
            with zipfile.ZipFile(path) as zf:
                zf.extractall(tmp)
            md = _find_skill_md(tmp)
            files = sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file())[:40]
        elif path.is_file() and path.suffix.lower() in {".md", ".markdown"}:
            kind = "md"
            md = path
            files = [path.name]
        elif path.is_dir():
            kind = "folder"
            md = _find_skill_md(path)
            files = sorted(str(p.relative_to(path)) for p in path.rglob("*") if p.is_file())[:40]
        else:
            raise SystemExit(f"[err] not a skill source (folder, SKILL.md, or zip): {src}")
        if md is None or not md.is_file():
            raise SystemExit("[err] no SKILL.md in source")
        text = md.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        name = meta.get("name") or (md.parent.name if kind != "md" else path.stem)
        return {
            "kind": kind,
            "name": name,
            "description": meta.get("description") or "",
            "files": files,
            "body": text[:8000],
            "path": str(path),
        }
    finally:
        if tmp and tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def import_skill(src: str) -> str:
    seed_catalog()
    path = Path(src).expanduser().resolve()
    tmp = None
    try:
        if path.is_file() and path.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="dt-skill-"))
            with zipfile.ZipFile(path) as zf:
                zf.extractall(tmp)
            md = _find_skill_md(tmp)
            if md is None:
                raise SystemExit("[err] zip has no SKILL.md")
            path = md.parent
        elif path.is_file() and path.suffix.lower() in {".md", ".markdown"}:
            meta = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            name = meta.get("name") or path.stem
            dest = catalog_dir() / name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest / "SKILL.md")
            return name
        elif path.is_file() and path.name == "SKILL.md":
            path = path.parent
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            md = _find_skill_md(path) if path.is_dir() else None
            if md is None:
                raise SystemExit(f"[err] not a skill source (folder, SKILL.md, or zip): {src}")
            path = md.parent
        meta = parse_frontmatter((path / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
        name = meta.get("name") or path.name
        dest = catalog_dir() / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(path, dest)
        return name
    finally:
        if tmp and tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def skill_body(name: str) -> str:
    path = catalog_dir() / name / "SKILL.md"
    if not path.is_file():
        raise SystemExit(f"[err] unknown skill: {name}")
    return path.read_text(encoding="utf-8", errors="replace")


def set_enabled(name: str, who: str, on: bool) -> dict:
    seed_catalog()
    names = {r["name"] for r in list_catalog()}
    if name not in names:
        raise SystemExit(f"[err] unknown skill: {name}")
    if who not in {"trigger", "bullet"}:
        raise SystemExit("[err] who must be trigger or bullet")
    cfg = load_config()
    bucket = cfg[who]
    if on and name not in bucket:
        bucket.append(name)
    if not on and name in bucket:
        if who == "trigger" and name in CORE:
            raise SystemExit(f"[err] core skill {name} stays on trigger")
        bucket.remove(name)
    save_config(cfg)
    return cfg


def enabled(who: str) -> list[str]:
    seed_catalog()
    cfg = load_config()
    have = {r["name"] for r in list_catalog()}
    names = [n for n in cfg.get(who, []) if n in have]
    if who == "trigger":
        for core in reversed(CORE):
            if core in have and core not in names:
                names.insert(0, core)
    return names


def install_into(dest: Path, names: list[str]) -> Path:
    seed_catalog()
    target = dest / ".opencode" / "skills"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    cat = catalog_dir()
    for name in names:
        src = cat / name
        if (src / "SKILL.md").is_file():
            shutil.copytree(src, target / name, dirs_exist_ok=True)
    return target


def instruction_paths(names: list[str]) -> list[str]:
    return [f".opencode/skills/{n}/SKILL.md" for n in names]


def write_opencode_json(dest: Path, names: list[str]) -> Path:
    path = dest / "opencode.json"
    instr = instruction_paths(names)
    payload = {"$schema": "https://opencode.ai/config.json", "instructions": instr}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def log_use(name: str, skill: str, ok: bool, detail: str = "", who: str = "trigger") -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "dt": name,
        "skill": skill,
        "who": who,
        "ok": bool(ok),
        "detail": detail,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_log(limit: int = 40, skill: str = "", name: str = "", ok: str = "") -> list[dict]:
    path = log_path()
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if skill and row.get("skill") != skill:
            continue
        if name and row.get("dt") != name:
            continue
        if ok == "yes" and not row.get("ok"):
            continue
        if ok == "no" and row.get("ok"):
            continue
        rows.append(row)
    return rows[-limit:]


def teach(name: str, skills: list[str], text: str = "") -> str:
    seed_catalog()
    data = load(find_dt(name))
    run = data.get("run") or ""
    have = {r["name"] for r in list_catalog()}
    missing = [s for s in skills if s not in have]
    if missing:
        raise SystemExit(f"[err] unknown skill: {', '.join(missing)}")
    cfg = load_config()
    for s in skills:
        if s not in cfg["bullet"]:
            cfg["bullet"].append(s)
    save_config(cfg)
    listed = ", ".join(skills)
    msg = text.strip() or (
        f"Learn and use these skills (OpenCode skill tool / SKILL.md): {listed}. "
        "Follow them for this workspace."
    )
    log_use(data.get("name") or name, ",".join(skills), True, "taught to bullet", who="bullet")
    data.setdefault("skills_taught", [])
    if not isinstance(data["skills_taught"], list):
        data["skills_taught"] = []
    for s in skills:
        if s not in data["skills_taught"]:
            data["skills_taught"].append(s)
    data["updated_at"] = now_iso()
    save(find_dt(name), data)
    return msg
