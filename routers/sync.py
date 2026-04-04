"""
Sync Snapshot endpoints — PYFIX License Server
================================================
  POST /sync/snapshot          → Recibe y almacena el backup del POS
  GET  /sync/snapshot/{key}    → Entrega el backup al POS que restaura
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import SyncSnapshot

router = APIRouter(prefix="/sync", tags=["sync"])


class SnapshotPushRequest(BaseModel):
    license_key: str
    device_id:   str
    payload:     str   # JSON serializado
    stats:       dict


@router.post("/snapshot")
def store_snapshot(data: SnapshotPushRequest, db: Session = Depends(get_db)):
    """Recibe y almacena el snapshot de datos de un negocio."""
    if not data.license_key or len(data.license_key) < 6:
        raise HTTPException(400, "license_key inválida")

    now = datetime.now(timezone.utc)

    existing = db.query(SyncSnapshot).filter(
        SyncSnapshot.license_key == data.license_key
    ).first()

    if existing:
        existing.device_id  = data.device_id
        existing.payload    = data.payload
        existing.stats      = json.dumps(data.stats)
        existing.updated_at = now
    else:
        db.add(SyncSnapshot(
            license_key = data.license_key,
            device_id   = data.device_id,
            payload     = data.payload,
            stats       = json.dumps(data.stats),
            created_at  = now,
            updated_at  = now,
        ))

    db.commit()
    return {"ok": True, "updated_at": now.isoformat()}


@router.get("/snapshot/{license_key}")
def get_snapshot(license_key: str, db: Session = Depends(get_db)):
    """Devuelve el snapshot más reciente de una licencia."""
    if not license_key or len(license_key) < 6:
        raise HTTPException(400, "license_key inválida")

    snap = db.query(SyncSnapshot).filter(
        SyncSnapshot.license_key == license_key
    ).first()

    if not snap:
        raise HTTPException(
            404,
            "No existe respaldo en la nube para esta licencia. "
            "Sube los datos primero desde el equipo original."
        )

    return {
        "ok":         True,
        "device_id":  snap.device_id,
        "stats":      json.loads(snap.stats) if snap.stats else {},
        "payload":    snap.payload,
        "updated_at": snap.updated_at.isoformat(),
    }
