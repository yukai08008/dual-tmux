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
    return f"~/{user}/sessions"
