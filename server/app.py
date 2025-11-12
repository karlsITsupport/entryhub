import os, json
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, create_engine, Session, select
from datetime import datetime, timezone, timedelta
from fastapi.middleware.cors import CORSMiddleware

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
# Datenmodell für Geräte in der Datenbank
# --------------------------------------------------------------------
class Device(SQLModel, table=True):
    entrypoint: str = Field(primary_key=True)
    location: Optional[str] = None
    ip: Optional[str] = None
    mac_address: Optional[str] = None
    hardware: Optional[str] = None
    access_type: Optional[str] = None
    token: str
    notes: Optional[str] = None
    last_seen: Optional[datetime] = None
    hostname: Optional[str] = None
    uptime_s: Optional[int] = None
    load1: Optional[float] = None
    mem_free_mb: Optional[int] = None
    agent_ver: Optional[str] = None


# --------------------------------------------------------------------
# Eingehender Heartbeat
# --------------------------------------------------------------------
class HeartbeatIn(BaseModel):
    entrypoint: str
    hostname: Optional[str] = None
    ts: Optional[datetime] = None
    uptime_s: Optional[int] = None
    load1: Optional[float] = None
    mem_free_mb: Optional[int] = None
    agent: Optional[dict] = None


# --------------------------------------------------------------------
# API-Ausgabe
# --------------------------------------------------------------------
class DeviceOut(BaseModel):
    entrypoint: str
    location: Optional[str]
    ip: Optional[str]
    mac_address: Optional[str]
    hardware: Optional[str]
    access_type: Optional[str]
    notes: Optional[str]
    last_seen: Optional[datetime]
    online: bool
    hostname: Optional[str]
    uptime_s: Optional[int]
    load1: Optional[float]
    mem_free_mb: Optional[int]
    agent_ver: Optional[str]


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
def post_heartbeat(payload: HeartbeatIn, device: Device = Depends(auth_device)):
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

