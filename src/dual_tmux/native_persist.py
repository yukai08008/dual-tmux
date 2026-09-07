"""Exact, append-only session snapshots for Codex and Claude Code.

Only the JSONL belonging to a frozen UUID is copied.  Credentials, global
configuration and every other session remain outside this persistence tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from . import agent_sessions
from .agentclient import normalize_name
from .paths import home_dir

SCHEMA = 1
TOOLS = {"codex", "claude"}
REVISION_RE = re.compile(r"^[0-9a-f]{64}$")


def persist_root() -> Path:
    from .hotfix import sessions_home

    return sessions_home() / "native"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_relative(raw: str) -> Path:
    value = PurePosixPath(raw)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise SystemExit("[err] native snapshot contains an unsafe relative path")
    if value.suffix != ".jsonl":
        raise SystemExit("[err] native snapshot payload must be JSONL")
    return Path(*value.parts)


def _session_root(tool: str, home: Path) -> Path:
    if tool == "codex":
        return home / ".codex" / "sessions"
    if tool == "claude":
        return home / ".claude" / "projects"
    raise ValueError(f"unsupported native session tool: {tool}")


def _record(path: Path, tool: str):
    parser = (
        agent_sessions._codex_record
        if tool == "codex"
        else agent_sessions._claude_record
    )
    return parser(path)


def locate_session(
    tool: str, session_id: str, *, home: Path | None = None
) -> Path | None:
    """Locate exactly one native JSONL for a UUID, failing closed on duplicates."""
    tool = normalize_name(tool)
    sid = (session_id or "").strip()
    if tool not in TOOLS or not agent_sessions.UUID_RE.fullmatch(sid):
        return None
    base = home or Path.home()
    root = _session_root(tool, base)
    hits: list[Path] = []
    if root.is_dir():
        for path in root.rglob("*.jsonl"):
            if path.is_symlink():
                continue
            record = _record(path, tool)
            if record and record.session_id == sid:
                hits.append(path)
    if len(hits) > 1:
        raise SystemExit(
            f"[err] native_session_conflict: {tool} {sid} has duplicate stores"
        )
    return hits[0] if hits else None


def _validated_payload(path: Path, tool: str, session_id: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"[err] native snapshot payload is not a regular file: {path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"[err] native snapshot read failed: {path}") from exc
    seen: set[str] = set()
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"[err] native snapshot has truncated JSONL: {path}"
            ) from exc
        if not isinstance(row, dict):
            raise SystemExit(
                f"[err] native snapshot contains a non-object record: {path}"
            )
        if tool == "codex" and row.get("type") == "session_meta":
            payload = row.get("payload") or {}
            value = payload.get("session_id") or payload.get("id")
            if value:
                seen.add(str(value))
        elif tool == "claude" and row.get("sessionId"):
            seen.add(str(row["sessionId"]))
    if seen != {session_id}:
        raise SystemExit(
            f"[err] native snapshot UUID mismatch: expected {session_id}, found {sorted(seen)}"
        )
    return raw


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def export_session(
    info: dict,
    source_client: str,
    *,
    source_instance: str = "",
    generation: int = 0,
    namespace: str = "",
    root: Path | None = None,
    home: Path | None = None,
) -> Path | None:
    """Export one frozen native UUID; return active manifest only when changed."""
    tool = normalize_name(str(info.get("tool") or ""))
    sid = str(info.get("session_id") or "").strip()
    if tool not in TOOLS or not info.get("frozen_at"):
        return None
    from .identity import legal_source

    namespace = namespace or source_client
    if not legal_source(source_client) or not legal_source(namespace):
        raise SystemExit("[err] native snapshot source Client is invalid")
    path = locate_session(tool, sid, home=home)
    if path is None:
        raise SystemExit(
            f"[err] frozen {tool} session {sid} is missing from its local store"
        )
    base_home = home or Path.home()
    store_root = _session_root(tool, base_home)
    try:
        relative = path.relative_to(store_root)
    except ValueError as exc:
        raise SystemExit("[err] native session escaped its allowed store") from exc
    raw = _validated_payload(path, tool, sid)
    revision = _sha256(raw)
    base = (root or persist_root()) / namespace / tool / sid
    active = base / "active.json"
    if active.is_file():
        try:
            current, _relative, snapshot = _load_active(active, tool, sid)
            if current.get("revision") == revision and snapshot == raw:
                return None
        except SystemExit:
            pass
    revision_dir = base / "revisions" / revision
    payload = revision_dir / "payload" / relative
    payload.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=payload.parent)
    tmp = Path(tmp_raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, payload)
    finally:
        tmp.unlink(missing_ok=True)
    client = info.get("agent_client") or {}
    manifest = {
        "schema": SCHEMA,
        "tool": tool,
        "session_id": sid,
        "source_client": source_client,
        "source_instance": source_instance,
        "generation": int(generation or 0),
        "revision": revision,
        "updated_at": int(time.time() * 1000),
        "frozen_at": str(info.get("frozen_at") or ""),
        "frozen_workdir": str(info.get("directory") or ""),
        "agent_client_version": str(client.get("version") or ""),
        "files": [
            {
                "path": relative.as_posix(),
                "size": len(raw),
                "sha256": revision,
            }
        ],
    }
    _atomic_json(revision_dir / "manifest.json", manifest)
    _atomic_json(active, manifest)
    revisions = base / "revisions"
    old = sorted(
        (path for path in revisions.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )[2:]
    for path in old:
        shutil.rmtree(path, ignore_errors=True)
    return active


def verify_export(
    info: dict,
    *,
    namespace: str,
    root: Path | None = None,
    home: Path | None = None,
) -> bool:
    """Confirm the durable active revision still equals the native live file."""
    tool = normalize_name(str(info.get("tool") or ""))
    sid = str(info.get("session_id") or "").strip()
    if tool not in TOOLS:
        return True
    local = locate_session(tool, sid, home=home)
    if local is None:
        return False
    active = (root or persist_root()) / namespace / tool / sid / "active.json"
    try:
        manifest, _relative, snapshot = _load_active(active, tool, sid)
        raw = _validated_payload(local, tool, sid)
    except SystemExit:
        return False
    return manifest.get("revision") == _sha256(raw) and snapshot == raw


def _load_active(path: Path, tool: str, sid: str) -> tuple[dict, Path, bytes]:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(
            f"[err] native snapshot manifest is not a regular file: {path}"
        )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[err] invalid native snapshot manifest: {path}") from exc
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("tool") != tool
        or manifest.get("session_id") != sid
        or not agent_sessions.UUID_RE.fullmatch(str(manifest.get("session_id") or ""))
    ):
        raise SystemExit(f"[err] native snapshot manifest identity mismatch: {path}")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise SystemExit(
            f"[err] native snapshot manifest must contain exactly one file: {path}"
        )
    relative = _safe_relative(str(files[0].get("path") or ""))
    revision = str(manifest.get("revision") or "")
    if not REVISION_RE.fullmatch(revision):
        raise SystemExit(f"[err] native snapshot revision is invalid: {path}")
    revision_dir = path.parent / "revisions" / revision
    sealed_path = revision_dir / "manifest.json"
    if sealed_path.is_symlink() or not sealed_path.is_file():
        raise SystemExit(f"[err] native snapshot revision manifest is missing: {path}")
    try:
        sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"[err] native snapshot revision manifest is missing: {path}"
        ) from exc
    if sealed != manifest:
        raise SystemExit(
            f"[err] native snapshot active/revision manifest mismatch: {path}"
        )
    payload = revision_dir / "payload" / relative
    payload_root = (revision_dir / "payload").resolve()
    try:
        payload.resolve().relative_to(payload_root)
    except ValueError as exc:
        raise SystemExit(
            f"[err] native snapshot payload escaped its revision: {path}"
        ) from exc
    raw = _validated_payload(payload, tool, sid)
    if (
        _sha256(raw) != files[0].get("sha256")
        or _sha256(raw) != revision
        or len(raw) != files[0].get("size")
    ):
        raise SystemExit(f"[err] native snapshot hash verification failed: {payload}")
    return manifest, relative, raw


def _candidates(tool: str, sid: str, root: Path) -> list[tuple[dict, Path, bytes]]:
    from .identity import legal_source

    rows = []
    if not root.is_dir():
        return rows
    for source in sorted(root.iterdir()):
        if not source.is_dir() or source.is_symlink() or not legal_source(source.name):
            continue
        active = source / tool / sid / "active.json"
        if active.is_file():
            rows.append(_load_active(active, tool, sid))
    return rows


def _newest(rows: list[tuple[dict, Path, bytes]]) -> tuple[dict, Path, bytes] | None:
    if not rows:
        return None
    winners = [
        row for row in rows if all(row[2].startswith(other[2]) for other in rows)
    ]
    if not winners:
        raise SystemExit("[err] native_snapshot_conflict: persisted histories diverge")
    return max(
        winners, key=lambda row: (len(row[2]), str(row[0].get("source_client") or ""))
    )


def inspect_session(
    info: dict, *, root: Path | None = None, home: Path | None = None
) -> dict:
    tool = normalize_name(str(info.get("tool") or ""))
    sid = str(info.get("session_id") or "").strip()
    if tool not in TOOLS:
        return {"status": "unsupported", "tool": tool or "opencode", "session_id": sid}
    local = locate_session(tool, sid, home=home)
    try:
        chosen = _newest(_candidates(tool, sid, root or persist_root()))
        if local and not chosen:
            status = "local"
        elif not local and chosen:
            status = "hub"
        elif not local:
            status = "missing"
        else:
            local_raw = _validated_payload(local, tool, sid)
            remote_raw = chosen[2]
            status = (
                "local"
                if local_raw.startswith(remote_raw)
                else ("newer" if remote_raw.startswith(local_raw) else "conflict")
            )
    except SystemExit:
        status = "conflict"
    return {"status": status, "tool": tool, "session_id": sid}


def import_session(
    info: dict,
    *,
    root: Path | None = None,
    home: Path | None = None,
    generation_check: Callable[[], None] | None = None,
    prepare_replace: Callable[[], None] | None = None,
) -> bool:
    """Converge a local UUID to the newest verified append-only snapshot."""
    tool = normalize_name(str(info.get("tool") or ""))
    sid = str(info.get("session_id") or "").strip()
    if tool not in TOOLS:
        return False
    chosen = _newest(_candidates(tool, sid, root or persist_root()))
    local = locate_session(tool, sid, home=home)
    if chosen is None:
        if local:
            return False
        raise SystemExit(
            f"[err] {tool} session {sid} is missing locally and on the Hub"
        )
    _manifest, relative, snapshot = chosen
    local_raw = _validated_payload(local, tool, sid) if local else b""
    if local_raw == snapshot or (local_raw and local_raw.startswith(snapshot)):
        return False
    if local_raw and not snapshot.startswith(local_raw):
        raise SystemExit(f"[err] native_snapshot_conflict: local {tool} {sid} diverged")
    if prepare_replace:
        prepare_replace()
    if generation_check:
        generation_check()
    base_home = home or Path.home()
    session_root = _session_root(tool, base_home)
    dest = local or (session_root / relative)
    try:
        dest.parent.resolve().relative_to(session_root.resolve())
    except ValueError as exc:
        raise SystemExit(
            "[err] native import destination escaped its session store"
        ) from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    if local:
        backup = (
            home_dir()
            / "native-backups"
            / tool
            / sid
            / f"{int(time.time() * 1000)}.jsonl"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local, backup)
    fd, tmp_raw = tempfile.mkstemp(prefix=f".{dest.name}.", dir=dest.parent)
    tmp = Path(tmp_raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(snapshot)
            handle.flush()
            os.fsync(handle.fileno())
        _validated_payload(tmp, tool, sid)
        if generation_check:
            generation_check()
        os.replace(tmp, dest)
        try:
            if generation_check:
                generation_check()
        except BaseException:
            if local_raw:
                fd, rollback_raw = tempfile.mkstemp(
                    prefix=f".{dest.name}.rollback.", dir=dest.parent
                )
                rollback = Path(rollback_raw)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(local_raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(rollback, dest)
                finally:
                    rollback.unlink(missing_ok=True)
            else:
                dest.unlink(missing_ok=True)
            raise
    finally:
        tmp.unlink(missing_ok=True)
    found = locate_session(tool, sid, home=base_home)
    if found is None or _sha256(_validated_payload(found, tool, sid)) != _sha256(
        snapshot
    ):
        raise SystemExit(f"[err] imported native session {sid} failed verification")
    return True
