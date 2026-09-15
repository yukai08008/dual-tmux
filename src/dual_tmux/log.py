from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .paths import events_path, home_dir
from .workpoint import now_iso

_RESERVED = {"ts", "kind", "pid", "sev", "cat"}

SEVERITIES = ("info", "warn", "error")
CATEGORIES = ("system", "trigger", "bullet")

# Keep last N event lines once the file passes the rotation size gate.
MAX_EVENT_LINES = 20_000
_ROTATE_BYTES = 8_000_000

# kind -> (category, severity, human label). Unregistered kinds fall back to
# suffix/prefix rules in meta(); registering here only adds display quality.
KIND_META: dict[str, tuple[str, str, str]] = {
    # --- system: tunnel lifecycle -------------------------------------
    "dt.new": ("system", "info", "隧道创建"),
    "dt.branch": ("system", "info", "隧道分支"),
    "dt.enter": ("system", "info", "进入隧道"),
    "dt.work": ("system", "info", "接入工作点"),
    "dt.resume": ("system", "info", "恢复/接管隧道"),
    "dt.drop": ("system", "info", "退出并收起隧道"),
    "dt.rm": ("system", "info", "删除隧道"),
    "dt.model.ok": ("system", "info", "模型替换成功"),
    "dt.model.fail": ("system", "error", "模型替换失败"),
    "hub.occupancy": ("system", "info", "占用声明（接管）"),
    "hub.occupancy.release": ("system", "info", "释放占用"),
    "hub.release": ("system", "info", "释放占用"),
    "hub.push": ("system", "info", "Hub 推送"),
    "hub.pull": ("system", "info", "Hub 拉取"),
    "hub.sync": ("system", "info", "Hub 双向同步"),
    "hub.push.ok": ("system", "info", "Hub 推送完成"),
    "hub.push.fail": ("system", "error", "Hub 推送失败"),
    "hub.sync.ok": ("system", "info", "Hub 同步完成"),
    "hub.sync.fail": ("system", "error", "Hub 同步失败"),
    "occupancy.fence.park": ("system", "warn", "他机占用，本机退出"),
    "occupancy.fence.fail": ("system", "error", "占用清退失败"),
    "transport.reconnect": ("system", "info", "建立管道"),
    "transport.reconnect.ok": ("system", "info", "管道重连成功"),
    "transport.reconnect.fail": ("system", "error", "管道重连失败"),
    "transport.reconcile": ("system", "info", "管道路由检查"),
    "freeze.start": ("system", "info", "固化开始"),
    "freeze.ok": ("system", "info", "固化完成"),
    "freeze.fail": ("system", "error", "固化失败"),
    "freeze.bound": ("system", "info", "DST 绑定提交"),
    "freeze.rejected": ("system", "warn", "固化被占用拒绝"),
    "freeze.commit_rejected": ("system", "warn", "绑定提交被拒"),
    "freeze.client.ok": ("system", "info", "Trigger 客户端固化"),
    "freeze.client.fail": ("system", "error", "Trigger 客户端固化失败"),
    "freeze.side.ok": ("system", "info", "单侧固化证明"),
    "freeze.side.fail": ("system", "error", "单侧固化失败"),
    "persist.export": ("system", "info", "快照导出"),
    "persist.export.fail": ("system", "error", "快照导出失败"),
    "persist.native.sync": ("system", "info", "原生会话同步"),
    "persist.native.sync.fail": ("system", "error", "原生会话同步失败"),
    "recovery.ok": ("system", "info", "健康恢复成功"),
    "recovery.fail": ("system", "error", "健康恢复失败"),
    "recovery.attempt.fail": ("system", "error", "恢复尝试失败"),
    "recovery.remote_import": ("system", "info", "远端会话导入"),
    "dt.daemon.start": ("system", "info", "daemon 启动"),
    "dt.daemon.stop": ("system", "info", "daemon 停止"),
    # --- trigger: user interaction layer ------------------------------
    "trigger.send": ("trigger", "info", "向 Trigger 发送指令"),
    "trigger.interrupt": ("trigger", "info", "打断 Trigger"),
    "trigger.turn.start": ("trigger", "info", "Trigger 回合开始"),
    "trigger.turn.end": ("trigger", "info", "Trigger 回合结束"),
    "trigger.stalled": ("trigger", "warn", "Trigger 疑似卡死"),
    "trigger.start.ok": ("trigger", "info", "Trigger 启动"),
    "trigger.start.fail": ("trigger", "error", "Trigger 启动失败"),
    "trigger.probe.fail": ("trigger", "warn", "Trigger 探测失败"),
    "bullet.send": ("trigger", "info", "命令 Bullet（注入工作点）"),
    "bullet.interrupt": ("trigger", "info", "打断 Bullet"),
    # --- bullet: remote agent lifecycle --------------------------------
    "bullet.start.ok": ("bullet", "info", "Bullet 启动"),
    "bullet.start.fail": ("bullet", "error", "Bullet 启动失败"),
    "bullet.run.start": ("bullet", "info", "Bullet 开始运行"),
    "bullet.run.end": ("bullet", "info", "Bullet 运行结束"),
    "bullet.stalled": ("bullet", "warn", "Bullet 疑似卡死"),
    "bullet.fence": ("bullet", "warn", "Bullet 孤儿实例清理"),
    "bullet.probe.fail": ("bullet", "warn", "Bullet 探测失败"),
}

_WARN_SUFFIXES = (".reject", ".violation", ".stalled", ".unconfirmed")
_SYSTEM_PREFIXES = (
    "hub.",
    "freeze.",
    "dt.",
    "recovery.",
    "occupancy.",
    "transport.",
    "fsm.",
    "persist.",
    "hotfix.",
    "cmd.",
    "feishu.",
    "ownership.",
)


def meta(kind: str) -> dict[str, str]:
    """Resolve category/severity/label for an event kind.

    Registered kinds win; anything else derives severity from the suffix and
    category from the prefix so old rows stay interpretable.
    """
    entry = KIND_META.get(kind)
    if entry:
        cat, sev, label = entry
        return {"cat": cat, "sev": sev, "label": label}
    low = kind.lower()
    sev = "info"
    if low.endswith(".fail"):
        sev = "error"
    elif low.endswith(_WARN_SUFFIXES):
        sev = "warn"
    cat = "system"
    if low.startswith("trigger."):
        cat = "trigger"
    elif low.startswith("bullet."):
        cat = "bullet"
    elif not any(low.startswith(prefix) for prefix in _SYSTEM_PREFIXES):
        cat = "system"
    return {"cat": cat, "sev": sev, "label": kind}


def label(kind: str) -> str:
    return meta(kind)["label"]


def emit(event: str, **fields: Any) -> dict:
    sev = fields.pop("sev", None)
    cat = fields.pop("cat", None)
    base = meta(event)
    if sev not in SEVERITIES:
        sev = base["sev"]
    if cat not in CATEGORIES:
        cat = base["cat"]
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
        "sev": sev,
        "cat": cat,
        **extra,
    }
    path = events_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    _maybe_rotate(path)
    return row


def read_events(
    limit: int = 50,
    kind: str = "",
    name: str = "",
    cat: str = "",
    sev: str = "",
) -> list[dict]:
    path = events_path()
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        row_kind = str(item.get("kind") or "")
        if kind and not row_kind.startswith(kind):
            continue
        if name and item.get("name") != name and item.get("dt") != name:
            continue
        if cat or sev:
            derived = meta(row_kind)
            if cat and str(item.get("cat") or derived["cat"]) != cat:
                continue
            if sev and str(item.get("sev") or derived["sev"]) != sev:
                continue
        rows.append(item)
    return rows[-limit:]


def _maybe_rotate(path: Path) -> None:
    try:
        if path.stat().st_size < _ROTATE_BYTES:
            return
    except OSError:
        return
    lines = [
        line
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    keep = lines[-MAX_EVENT_LINES:]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        "\n".join(keep) + ("\n" if keep else ""), encoding="utf-8"
    )
    os.replace(tmp, path)


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
