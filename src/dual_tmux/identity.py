from __future__ import annotations

SOURCE_HINT = "must start with tm_ then [A-Za-z0-9._-], e.g. tm_laptop (not hostname)"
USER_HINT = "person id [A-Za-z][A-Za-z0-9._-], e.g. ouc (not hostname, not tm_*)"


def legal_source(name: str) -> bool:
    if not name.startswith("tm_") or len(name) < 4:
        return False
    return all(c.isalnum() or c in "._-" for c in name[3:])


def legal_user(name: str) -> bool:
    if not name or name.startswith("tm_") or name in (".", ".."):
        return False
    if not name[0].isalpha():
        return False
    return all(c.isalnum() or c in "._-" for c in name)


def remote_sessions_root(user: str) -> str:
    if not legal_user(user):
        raise ValueError(f"user {USER_HINT}")
    return f"~/{user}/sessions"


def remote_dt_root(user: str) -> str:
    if not legal_user(user):
        raise ValueError(f"user {USER_HINT}")
    return f"~/{user}/dual-tmux"


def persist_local_root() -> str:
    return "~/sessions"


def persist_kind(kind: str) -> str:
    if kind not in {"tmux", "opencode"}:
        raise ValueError("kind must be tmux or opencode")
    return kind


def persist_local_kind(kind: str) -> str:
    return f"{persist_local_root()}/{persist_kind(kind)}"


def persist_hub_kind(user: str, kind: str) -> str:
    return f"{remote_sessions_root(user)}/{persist_kind(kind)}"


def persist_source_dir(kind: str, source: str, *, hub_user: str | None = None) -> str:
    if not legal_source(source):
        raise ValueError(f"source {SOURCE_HINT}")
    root = persist_hub_kind(hub_user, kind) if hub_user else persist_local_kind(kind)
    return f"{root}/{source}"


def persist_rsync_rel(user: str, kind: str) -> str:
    """rsync path on Server, relative to the ssh login home."""
    if not legal_user(user):
        raise ValueError(f"user {USER_HINT}")
    return f"{user}/sessions/{persist_kind(kind)}"
