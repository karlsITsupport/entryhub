import os, json
from datetime import datetime, timezone, timedelta
from typing import Optional
from server.models import Device, HeartbeatIn, DeviceOut
from fastapi import FastAPI, Header, HTTPException, Depends, Request, Form, Query
from sqlmodel import SQLModel, Field, create_engine, Session, select
from datetime import datetime, timezone, timedelta
from fastapi.middleware.cors import CORSMiddleware
import subprocess

# ...
def _as_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


DB_URL = os.getenv("HEARTBEAT_DB", "sqlite:///./heartbeats.db")
DEVICES_FILE = os.getenv("DEVICES_FILE", "server/devices.json")
ONLINE_GRACE_S = int(os.getenv("ONLINE_GRACE_S", "120"))

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


# --------------------------------------------------------------------
# Den letzten Block des Logs ausgeben
# --------------------------------------------------------------------

def classify_scan(block: list[str]) -> dict:
    result = {
        "barcode": None,
        "result": "unknown",
        "details": None,
        "lines": block,
    }

    for line in block:
        if "got barcode" in line:
            result["barcode"] = line.split("'")[1]

        if "access granted" in line:
            result["result"] = "granted"

        if "ticket suspended / reentrance" in line:
            result["result"] = "denied"
            result["details"] = "ticket suspended / reentrance"

        if "denied finaly by index" in line:
            result["result"] = "denied"
            result["details"] = line.split(" - ", 1)[1]

    return result


def extract_last_scan(lines: list[str]) -> list[str] | None:
    end = None
    start = None

    # 1) Ende finden
    for i in range(len(lines) - 1, -1, -1):
        if "INFO Main:100 - wait for barcode" in lines[i]:
            end = i
            break

    if end is None:
        return None

    # 2) Start finden (davor!)
    for j in range(end - 1, -1, -1):
        if "INFO EntryClient:701 - got barcode" in lines[j]:
            start = j
            break

    if start is None:
        return None

    return lines[start:end]


# --------------------------------------------------------------------
# FastAPI-App
# --------------------------------------------------------------------

app = FastAPI(title="EntryHub API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # oder trage hier deine genaue URL ein, z.B. "http://10.10.16.70"
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.get("/ping")
def ping():
    return {"status": "ok"}


# --------------------------------------------------------------------
# Die Route für Terminal-Befehle
# --------------------------------------------------------------------

@app.post("/api/v1/devices/{entrypoint}/exec")
def exec_cmd(entrypoint: str, action: str):
    with Session(engine) as s:
        d = s.get(Device, entrypoint)
        if not d or not d.ip:
            raise HTTPException(404, "device not found or no IP")

    result = subprocess.run(
        [
            "curl", "-s", "-X", "POST",
            f"http://{d.ip}/admin/ajax.php",
            "-d", f"function={action}"
        ],
        capture_output=True,
        text=True,
        timeout=5
    )

    return {
        "action": action,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# --------------------------------------------------------------------
# Das Log fetchen
# --------------------------------------------------------------------

@app.get("/api/v1/devices/{entrypoint}/last-scan")
def get_last_scan(entrypoint: str, lines: int = 200):
    with Session(engine) as s:
        d = s.get(Device, entrypoint)
        if not d or not d.ip:
            raise HTTPException(404, "device not found or no IP")

    cmd = f"tail -n {int(lines)} /var/log/korona/log.out"
    r = subprocess.run(
        [
            "curl", "-sS", "--fail",
            "-X", "POST", f"http://{d.ip}/admin/ajax.php",
            "--data-urlencode", "function=diag",
            "--data-urlencode", f"cmd={cmd}",
        ],
        capture_output=True,
        text=True,
        timeout=8
    )

    if r.returncode != 0:
        raise HTTPException(502, r.stderr.strip())

    out = (r.stdout or "").strip()
    if not out:
        raise HTTPException(502, "Pi call returned empty stdout")

    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        raise HTTPException(
            502,
            f"Pi call did not return JSON. First 200 chars: {out[:200]!r}"
        )

    # ajax.php liefert {"cmd": "...", "output": ["zeile", "zeile", ...]}
    out_lines = payload.get("output")
    if not isinstance(out_lines, list) or not out_lines:
        return {"found": False}

    log_lines = [str(x) for x in out_lines]

    block = extract_last_scan(log_lines)
    if not block:
        return {"found": False}

    return {"found": True, **classify_scan(block)}


# --------------------------------------------------------------------
# Die Diag-Route
# --------------------------------------------------------------------

@app.post("/api/v1/devices/{entrypoint}/diag")
def diag(entrypoint: str, cmd: str = Form(...)):
    with Session(engine) as s:
        d = s.get(Device, entrypoint)
        if not d or not d.ip:
            raise HTTPException(404, "device not found or no IP")

    r = subprocess.run(
        [
            "curl", "-sS", "--fail",
            "-X", "POST", f"http://{d.ip}/admin/ajax.php",
            "--data-urlencode", "function=diag",
            "--data-urlencode", f"cmd={cmd}",
        ],
        capture_output=True,
        text=True,
        timeout=8
    )

    if r.returncode != 0:
        raise HTTPException(502, f"Pi call failed: {r.stderr.strip()}")

    # r.stdout ist JSON von ajax.php (wenn du es so implementiert hast)
    return json.loads(r.stdout)


# --------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------

def load_devices():
    if not os.path.exists(DEVICES_FILE):
        return []
    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("devices", [])


def bootstrap_devices():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        for d in load_devices():
            if not s.get(Device, d["entrypoint"]):
                s.add(Device(**d))
        s.commit()


@app.on_event("startup")
def on_startup():
    bootstrap_devices()


def auth_device(authorization: Optional[str] = Header(default=None)) -> Device:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    with Session(engine) as s:
        dev = s.exec(select(Device).where(Device.token == token)).first()
        if not dev:
            raise HTTPException(status_code=401, detail="Invalid token")
        return dev


# --------------------------------------------------------------------
# Heartbeat-Endpoint
# --------------------------------------------------------------------

@app.post("/api/v1/heartbeat")
def post_heartbeat(
    payload: HeartbeatIn,
    device: Device = Depends(auth_device),
    request: Request = None,   # Request-Objekt dazu
):
    if payload.entrypoint != device.entrypoint:
        raise HTTPException(status_code=400, detail="entrypoint mismatch")
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        d = s.get(Device, device.entrypoint)
        d.last_seen = now
        d.hostname = payload.hostname or d.hostname
        d.uptime_s = payload.uptime_s
        d.load1 = payload.load1
        d.mem_free_mb = payload.mem_free_mb
        d.agent_ver = (payload.agent or {}).get("ver") if payload.agent else None
        if request is not None and request.client:
            d.ip = request.client.host      # hier kommt die „echte“ IP her
        s.add(d)
        s.commit()
    return {"status": "ok", "now": now.isoformat()}


# --------------------------------------------------------------------
# Geräte-Übersicht
# --------------------------------------------------------------------

@app.get("/api/v1/devices", response_model=list[DeviceOut])
def list_devices():
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        result = []
        for d in s.exec(select(Device)).all():
            ls = _as_aware_utc(d.last_seen)
            online = bool(ls and (now - ls) <= timedelta(seconds=ONLINE_GRACE_S))
            result.append(DeviceOut(
                entrypoint=d.entrypoint,
                location=d.location,
                ip=d.ip,
                mac_address=d.mac_address,
                hardware=d.hardware,
                access_type=d.access_type,
                notes=d.notes,
                last_seen=ls,
                online=online,
                hostname=d.hostname,
                uptime_s=d.uptime_s,
                load1=d.load1,
                mem_free_mb=d.mem_free_mb,
                agent_ver=d.agent_ver
            ))
    return result