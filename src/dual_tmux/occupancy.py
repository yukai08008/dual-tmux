"""TTL-less exclusive occupancy: last resume writer owns the trigger."""

from __future__ import annotations

import json
import time

from . import hub
from . import log as ev
from .config import AppConfig, load_config

SCRIPT = r"""
set -e
ROOT="$1"; NAME="$2"; ACTION="$3"; ME="$4"; INSTANCE="$5"
mkdir -p "$ROOT/occupancy" "$ROOT/locks" "$ROOT/ownership"
lock="$ROOT/locks/$NAME"
occ="$ROOT/occupancy/$NAME.json"
side="$ROOT/ownership/$NAME.json"
exec 9>>"$lock"
flock -x 9
python3 - "$occ" "$lock" "$side" "$NAME" "$ACTION" "$ME" "$INSTANCE" <<'PY'
import json,os,sys,tempfile,time
occ,lock,side,name,action,me,instance=sys.argv[1:]
now=int(time.time())
try:
 with open(occ) as f: data=json.load(f)
except Exception:
 data={}
parts=open(lock).read().strip().split('@') if os.path.exists(lock) else []
generation=int(parts[2]) if len(parts)>2 and parts[2].isdigit() else 0
holder=str(data.get('holder') or (parts[0] if parts else ''))
if action=='read':
 print(json.dumps({'ok':True,'schema':1,'name':name,'holder':holder,'claimed_at':int(data.get('claimed_at') or 0),'generation':generation}))
 raise SystemExit(0)
if action!='claim':
 print(json.dumps({'ok':False,'code':'invalid_action'})); raise SystemExit(9)
if holder != me:
 generation += 1
elif generation==0:
 generation = 1
data={'schema':1,'name':name,'holder':me,'claimed_at':now,'generation':generation}
os.makedirs(os.path.dirname(occ),exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.occupancy-',dir=os.path.dirname(occ))
with os.fdopen(fd,'w') as f: json.dump(data,f,separators=(',',':')); f.write('\n')
os.replace(tmp,occ)
with open(lock,'w') as f: f.write(f'{me}@{now}@{generation}\n')
side_value={'schema':2,'lease_protocol':2,'lease_ttl':86400,'name':name,'holder':me,'instance_id':instance,'generation':generation,'renewed_at':now,'expires_at':now+86400,'evidence':{},'handoff':None}
os.makedirs(os.path.dirname(side),exist_ok=True)
fd,tmp=tempfile.mkstemp(prefix='.ownership-',dir=os.path.dirname(side))
with os.fdopen(fd,'w') as f: json.dump(side_value,f,separators=(',',':')); f.write('\n')
os.replace(tmp,side)
print(json.dumps({'ok':True,**data}))
PY
"""


def _local(name: str, cfg: AppConfig) -> dict:
    now = int(time.time())
    return {
        "ok": True,
        "schema": 1,
        "name": name,
        "holder": cfg.client,
        "claimed_at": now,
        "generation": 1,
    }


def _remote(name: str, action: str, cfg: AppConfig | None = None) -> dict:
    cfg = cfg or load_config()
    if not cfg.hub_enabled:
        return _local(name, cfg)
    root = hub.remote_root(cfg)
    result = hub._run(
        hub.ssh_argv(cfg, connect_timeout=2)
        + [
            "bash",
            "-s",
            "--",
            root.removeprefix("~/"),
            name,
            action,
            cfg.client,
            hub.instance_id(),
        ],
        input=SCRIPT,
        timeout=8,
    )
    lines = (result.stdout or "").strip().splitlines()
    try:
        value = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        value = {}
    if not value:
        detail = (result.stderr or "occupancy failed").strip().splitlines()
        raise SystemExit(
            f"[err] hub occupancy: {detail[-1] if detail else 'failed'}"
        )
    return value


def read_occupancy(name: str, cfg: AppConfig | None = None) -> dict:
    value = _remote(name, "read", cfg=cfg)
    if not value.get("ok"):
        raise SystemExit(
            f"[err] occupancy read rejected: {value.get('code') or 'unknown'}"
        )
    return value


def claim_occupancy(name: str, cfg: AppConfig | None = None) -> dict:
    """Declare this Client as the single active trigger. Last writer wins."""
    value = _remote(name, "claim", cfg=cfg)
    if not value.get("ok"):
        raise SystemExit(
            f"[err] occupancy claim rejected: {value.get('code') or 'unknown'}"
        )
    ev.emit(
        "hub.occupancy",
        name=name,
        holder=str(value.get("holder") or ""),
        generation=int(value.get("generation") or 0),
    )
    return value


def foreign_holder(occupancy: dict, client: str) -> bool:
    holder = str(occupancy.get("holder") or "")
    return bool(holder and holder != client)
