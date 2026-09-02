from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import cron as cron_ops
from . import log as ev
from .config import AppConfig, load_config
from .identity import legal_source, legal_user, persist_rsync_rel, persist_source_dir
from .paths import home_dir
from .sshutil import SshTarget

HOTFIX_ID = "persist-tenant-v1"
STAMP_NAME = "hotfix.stamp"


@dataclass
class Step:
    id: str
    ok: bool
    detail: str
    changed: bool = False


def stamp_path() -> Path:
    return home_dir() / STAMP_NAME


def persist_dir() -> Path:
    return Path(
        os.environ.get("DT_PERSIST_CONFIG", Path.home() / ".config" / "session-persist")
    ).expanduser()


def persist_name_path() -> Path:
    return persist_dir() / "name"


def persist_user_path() -> Path:
    return persist_dir() / "user"


def sessions_home() -> Path:
    raw = os.environ.get("DT_SESSIONS_HOME", "")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "sessions"


def crontab_text() -> str:
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=8, check=False
        )
    except subprocess.TimeoutExpired:
        return ""
    return result.stdout or ""


def _write_text(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text if text.endswith("\n") else text + "\n"
    if path.is_file() and path.read_text() == body:
        return False
    path.write_text(body)
    return True


def sync_persist_identity(cfg: AppConfig) -> Step:
    if not legal_source(cfg.client) or (cfg.hub_enabled and not legal_user(cfg.user)):
        return Step("identity", False, "dt config client/user invalid", False)
    persist_dir().mkdir(parents=True, exist_ok=True)
    changed = False
    name_path = persist_name_path()
    current = name_path.read_text().strip() if name_path.is_file() else ""
    if not legal_source(current):
        changed = _write_text(name_path, cfg.client) or changed
        current = cfg.client
    if not cfg.hub_enabled:
        return Step("identity", True, f"{current} / local-only", changed)
    user_path = persist_user_path()
    user_now = user_path.read_text().strip() if user_path.is_file() else ""
    if user_now != cfg.user:
        changed = _write_text(user_path, cfg.user) or changed
        user_now = cfg.user
    return Step("identity", True, f"{current} / {user_now}", changed)


def ensure_local_trees(cfg: AppConfig) -> Step:
    (sessions_home() / "tmux" / cfg.client).mkdir(parents=True, exist_ok=True)
    (sessions_home() / "opencode" / cfg.client).mkdir(parents=True, exist_ok=True)
    return Step(
        "local-trees",
        True,
        f"{persist_source_dir('tmux', cfg.client)} + {persist_source_dir('opencode', cfg.client)}",
        False,
    )


def _ssh_argv(cfg: AppConfig) -> list[str]:
    target = SshTarget(cfg.server, cfg.ssh_port)
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ControlMaster=no",
        *target.extra_args,
        target.dest,
    ]


def ensure_hub_trees(cfg: AppConfig) -> Step:
    rel_tmux = persist_rsync_rel(cfg.user, "tmux")
    rel_oc = persist_rsync_rel(cfg.user, "opencode")
    cmd = f"mkdir -p ~/{rel_tmux} ~/{rel_oc}"
    try:
        result = subprocess.run(
            _ssh_argv(cfg) + [cmd], capture_output=True, text=True, timeout=12, check=False
        )
    except subprocess.TimeoutExpired:
        return Step("hub-trees", False, "ssh mkdir timed out", False)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "ssh mkdir failed").strip().splitlines()
        return Step("hub-trees", False, err[-1] if err else "ssh mkdir failed", False)
    return Step("hub-trees", True, f"~/{rel_tmux} ~/{rel_oc}", True)


def _cron_has(marker: str) -> bool:
    return any(marker in row and not row.strip().startswith("#") for row in crontab_text().splitlines())


def _install_cron_line(line: str, marker: str) -> bool:
    if _cron_has(marker):
        return False
    body = crontab_text().rstrip()
    text = f"{body}\n{line}\n" if body else f"{line}\n"
    try:
        result = subprocess.run(
            ["crontab", "-"], input=text, capture_output=True, text=True, timeout=8, check=False
        )
    except subprocess.TimeoutExpired:
        raise SystemExit("[err] crontab timed out")
    if result.returncode != 0:
        err = (result.stderr or "crontab failed").strip().splitlines()
        raise SystemExit(f"[err] crontab: {err[-1] if err else 'failed'}")
    return True


def persist_bin(kind: str) -> Path:
    return home_dir() / "bin" / f"dt-persist-{kind}"


def persist_script(kind: str, host: str, user: str) -> str:
    extra = ""
    if kind == "opencode":
        extra = "command -v opencode >/dev/null && command -v sqlite3 >/dev/null || true"
    exclude = "--exclude='save/'"
    if kind == "tmux":
        exclude += " --exclude='restore/'"
    rel = f"{user}/sessions/{kind}"
    lines = [
        "#!/usr/bin/env bash",
        "set -u",
        'export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/bin:$PATH"',
        f'HOST="${{1:-{host}}}"',
        'grep -Fqx "server = \\"$HOST\\"" "$HOME/.dual-tmux/config.toml" 2>/dev/null || exit 0',
        'ME="$(tr -d \'[:space:]\' < "$HOME/.config/session-persist/name" 2>/dev/null || true)"',
        'case "$ME" in tm_*) ;; *) exit 0 ;; esac',
        f'ROOT="$HOME/sessions/{kind}"',
        'LOCAL="$ROOT/$ME"',
        f'LOCK="$HOME/.dual-tmux/locks/persist-{kind}"',
        'mkdir -p "$LOCAL" "$(dirname "$LOCK")"',
        'mkdir "$LOCK" >/dev/null 2>&1 || exit 0',
        "trap 'rmdir \"$LOCK\" 2>/dev/null' EXIT",
    ]
    if extra:
        lines.append(extra)
    lines.extend(
        [
            f'rsync -a --delete {exclude} "$LOCAL"/ "$HOST:{rel}/$ME/" >/dev/null 2>&1 || exit 1',
            f'names="$(ssh -o BatchMode=yes "$HOST" "for d in \\"\\$HOME/{rel}\\"/*/; do [ -d \\"\\$d\\" ] || continue; b=\\$(basename \\"\\$d\\"); case \\"\\$b\\" in tm_*) printf \'%s\\\\n\' \\"\\$b\\" ;; esac; done" 2>/dev/null || true)"',
            "while IFS= read -r n; do",
            '    [ -n "$n" ] || continue',
            '    [ "$n" = "$ME" ] && continue',
            '    mkdir -p "$ROOT/$n"',
            f'    rsync -a "$HOST:{rel}/$n/" "$ROOT/$n/" >/dev/null 2>&1 || true',
            'done <<< "$names"',
            "exit 0",
            "",
        ]
    )
    return "\n".join(lines)


def install_persist_sync(cfg: AppConfig) -> Step:
    changed = False
    for kind in ("tmux", "opencode"):
        path = persist_bin(kind)
        body = persist_script(kind, cfg.server, cfg.user)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text() != body:
            path.write_text(body)
            path.chmod(0o755)
            changed = True
        marker = f"dt-persist-{kind}"
        line = f"* * * * * {path} >/dev/null 2>&1"
        try:
            if _install_cron_line(line, marker):
                changed = True
        except SystemExit as exc:
            return Step("persist-cron", False, str(exc), changed)
    return Step("persist-cron", True, f"{persist_bin('tmux')} + {persist_bin('opencode')}", changed)


def uninstall_persist_sync() -> Step:
    before = crontab_text()
    rows = [row for row in before.splitlines() if "dt-persist-tmux" not in row and "dt-persist-opencode" not in row]
    after = ("\n".join(rows) + "\n") if rows else ""
    if after == before:
        return Step("persist-cron", True, "disabled in local-only mode", False)
    try:
        result = subprocess.run(
            ["crontab", "-"],
            input=after,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Step("persist-cron", False, "crontab update timed out", False)
    if result.returncode != 0:
        return Step("persist-cron", False, (result.stderr or "crontab failed").strip(), False)
    return Step("persist-cron", True, "removed remote persist sync", True)


def install_tick() -> Step:
    wanted = cron_ops.line()
    if wanted in cron_ops.current().splitlines():
        return Step("tick-cron", True, wanted, False)
    cron_ops.install()
    return Step("tick-cron", True, wanted, True)


def install_feishu_daemon() -> Step:
    from . import daemon_service
    from .feishu import CredentialVault, FeishuError

    try:
        installation = CredentialVault().load()
    except FeishuError:
        installation = {}
    if not installation or not installation.get("active", True):
        return Step("feishu-daemon", True, "no active PersonalAgent", False)
    path = daemon_service.launchd_path() if __import__("platform").system() == "Darwin" else daemon_service.systemd_path()
    changed = not path.is_file()
    try:
        installed = daemon_service.install()
    except SystemExit as exc:
        return Step("feishu-daemon", False, str(exc), False)
    return Step("feishu-daemon", True, str(installed), changed)


def apply(cfg: AppConfig | None = None, *, ssh: bool = True) -> list[Step]:
    cfg = cfg or load_config()
    steps = [
        sync_persist_identity(cfg),
        ensure_local_trees(cfg),
        install_tick(),
        install_feishu_daemon(),
        install_persist_sync(cfg) if cfg.hub_enabled else uninstall_persist_sync(),
    ]
    if ssh and cfg.hub_enabled:
        steps.append(ensure_hub_trees(cfg))
    stamp_path().parent.mkdir(parents=True, exist_ok=True)
    stamp_path().write_text(HOTFIX_ID + "\n")
    ev.emit("hotfix.ok", id=HOTFIX_ID, changed=sum(1 for s in steps if s.changed))
    return steps


def needed() -> bool:
    path = stamp_path()
    if not path.is_file():
        return True
    return path.read_text().strip() != HOTFIX_ID
