from __future__ import annotations

SOURCE_HINT = "must start with tm_ then [A-Za-z0-9._-], e.g. tm_laptop (not hostname)"


def legal_source(name: str) -> bool:
    if not name.startswith("tm_") or len(name) < 4:
        return False
    return all(c.isalnum() or c in "._-" for c in name[3:])
