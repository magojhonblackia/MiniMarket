"""
Panel de administración — solo accesible con ADMIN_SECRET_KEY.
Permite gestionar tenants, ver estadísticas y revocar licencias.
"""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import Tenant, Activation
from config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Dependencia de autenticación admin ───────────────────────

def require_admin(x_admin_key: str = Header(...)):
    if x_admin_key != settings.ADMIN_SECRET_KEY:
        raise HTTPException(403, "Acceso denegado")


# ── Schemas ───────────────────────────────────────────────────

class TenantSummary(BaseModel):
    id: str
    business_name: str
    owner_name: str
    email: str
    phone: str | None
    license_key: str
    plan: str
    trial_ends_at: datetime
    paid_until: datetime | None
    is_active: bool
    created_at: datetime
    active_devices: int


class ExtendTrialRequest(BaseModel):
    days: int = 30


class ChangePlanRequest(BaseModel):
    plan: str          # trial | basic | pro
    paid_until: datetime | None = None


class StatsResponse(BaseModel):
    total_tenants: int
    active_tenants: int
    trial_tenants: int
    paid_tenants: int
    expired_tenants: int


# ── Endpoints ─────────────────────────────────────────────────

@router.get("/tenants", response_model=list[TenantSummary], dependencies=[Depends(require_admin)])
def list_tenants(db: Session = Depends(get_db)):
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    result = []
    for t in tenants:
        active_devices = db.query(Activation).filter(
            Activation.tenant_id == t.id,
            Activation.is_active == True,
        ).count()
        result.append(TenantSummary(
            id=str(t.id),
            business_name=t.business_name,
            owner_name=t.owner_name,
            email=t.email,
            phone=t.phone,
            license_key=t.license_key,
            plan=t.plan,
            trial_ends_at=t.trial_ends_at,
            paid_until=t.paid_until,
            is_active=t.is_active,
            created_at=t.created_at,
            active_devices=active_devices,
        ))
    return result


@router.get("/stats", response_model=StatsResponse, dependencies=[Depends(require_admin)])
def get_stats(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    total    = db.query(Tenant).count()
    active   = db.query(Tenant).filter(Tenant.is_active == True).count()
    trial    = db.query(Tenant).filter(
        Tenant.plan == "trial",
        Tenant.trial_ends_at > now,
        Tenant.is_active == True,
    ).count()
    paid     = db.query(Tenant).filter(
        Tenant.plan != "trial",
        Tenant.paid_until > now,
        Tenant.is_active == True,
    ).count()
    expired  = db.query(Tenant).filter(
        Tenant.trial_ends_at < now,
        Tenant.paid_until == None,
        Tenant.is_active == True,
    ).count()

    return StatsResponse(
        total_tenants=total,
        active_tenants=active,
        trial_tenants=trial,
        paid_tenants=paid,
        expired_tenants=expired,
    )


@router.post("/tenants/{tenant_id}/extend-trial", dependencies=[Depends(require_admin)])
def extend_trial(tenant_id: str, req: ExtendTrialRequest, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant no encontrado")

    now = datetime.now(timezone.utc)
    base = max(tenant.trial_ends_at, now)
    tenant.trial_ends_at = base + timedelta(days=req.days)
    db.commit()
    return {"message": f"Trial extendido {req.days} días. Nuevo vencimiento: {tenant.trial_ends_at}"}


@router.patch("/tenants/{tenant_id}/plan", dependencies=[Depends(require_admin)])
def change_plan(tenant_id: str, req: ChangePlanRequest, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant no encontrado")

    if req.plan not in ("trial", "basic", "pro"):
        raise HTTPException(400, "Plan inválido. Opciones: trial, basic, pro")

    tenant.plan = req.plan
    if req.paid_until:
        tenant.paid_until = req.paid_until
    db.commit()
    return {"message": f"Plan actualizado a '{req.plan}'"}


@router.delete("/tenants/{tenant_id}/activate", dependencies=[Depends(require_admin)])
def revoke_license(tenant_id: str, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant no encontrado")

    tenant.is_active = False
    db.commit()
    return {"message": "Licencia revocada"}


@router.delete("/tenants/{tenant_id}/devices/{hardware_id}", dependencies=[Depends(require_admin)])
def deactivate_device(tenant_id: str, hardware_id: str, db: Session = Depends(get_db)):
    activation = db.query(Activation).filter(
        Activation.tenant_id == tenant_id,
        Activation.hardware_id == hardware_id,
    ).first()
    if not activation:
        raise HTTPException(404, "Dispositivo no encontrado")

    activation.is_active = False
    db.commit()
    return {"message": "Dispositivo desactivado"}
