from __future__ import annotations

import json
import os
import time
from typing import Any

from .paths import events_path, home_dir
from .workpoint import now_iso


_RESERVED = {"ts", "kind", "pid"}


def emit(event: str, **fields: Any) -> dict:
    home_dir().mkdir(parents=True, exist_ok=True)
    extra = {}
    for key, value in fields.items():
        if value is None or key in _RESERVED:
            continue
        extra[key] = value
    row = {
        "ts": now_iso(),
        "kind": event,
        "pid": os.getpid(),
        **extra,
    }
    path = events_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def read_events(limit: int = 50, kind: str = "", name: str = "") -> list[dict]:
    path = events_path()
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind and not str(item.get("kind") or "").startswith(kind):
            continue
        if name and item.get("name") != name and item.get("dt") != name:
            continue
        rows.append(item)
    return rows[-limit:]


def timed(kind: str, **fields: Any):
    class _Span:
        def __init__(self) -> None:
            self.start = time.monotonic()
            self.fields = dict(fields)
            emit(f"{kind}.start", **self.fields)

        def ok(self, **extra: Any) -> None:
            emit(f"{kind}.ok", ms=int((time.monotonic() - self.start) * 1000), **self.fields, **extra)

        def fail(self, error: str, **extra: Any) -> None:
            emit(
                f"{kind}.fail",
                ms=int((time.monotonic() - self.start) * 1000),
                error=error,
                **self.fields,
                **extra,
            )

    return _Span()
