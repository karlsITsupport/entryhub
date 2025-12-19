from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field, create_engine, Session, select
from pydantic import BaseModel


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

