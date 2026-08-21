from __future__ import annotations


def legal_source(name: str) -> bool:
    return name.startswith("tm_") and all(c.isalnum() or c in "._-" for c in name[3:])
