"""
Validación y activación de licencias — llamado desde la app PYFIX en cada PC.
"""
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import Tenant, Activation
from config import settings

router = APIRouter(prefix="/license", tags=["license"])


# ── Schemas ───────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    license_key: str
    hardware_id: str          # hash único del PC (MAC + hostname)
    hostname: str | None = None


class LicenseStatus(BaseModel):
    valid: bool
    plan: str
    status: str               # active | trial | grace | degraded | blocked
    days_remaining: int | None
    business_name: str
    owner_name: str
    message: str
    # Permisos según estado
    can_use_reports: bool
    can_use_all_payments: bool
    full_access: bool


class ActivateRequest(BaseModel):
    license_key: str
    hardware_id: str
    hostname: str | None = None


class ActivateResponse(BaseModel):
    activated: bool
    message: str


# ── Helpers ───────────────────────────────────────────────────

def _compute_status(tenant: Tenant) -> dict:
    now = datetime.now(timezone.utc)

    # Plan pagado vigente
    if tenant.paid_until and tenant.paid_until > now:
        days = (tenant.paid_until - now).days
        return {
            "status": "active",
            "days_remaining": days,
            "can_use_reports": True,
            "can_use_all_payments": True,
            "full_access": True,
            "message": f"Licencia activa. Vence en {days} días.",
        }

    # Trial vigente
    if tenant.trial_ends_at > now:
        days = (tenant.trial_ends_at - now).days
        return {
            "status": "trial",
            "days_remaining": days,
            "can_use_reports": True,
            "can_use_all_payments": True,
            "full_access": True,
            "message": f"Período de prueba: {days} días restantes.",
        }

    # Calcular días desde que venció
    expiry = tenant.paid_until if tenant.paid_until else tenant.trial_ends_at
    days_expired = (now - expiry).days

    if days_expired <= settings.GRACE_PERIOD_DAYS:
        return {
            "status": "grace",
            "days_remaining": -(days_expired),
            "can_use_reports": True,
            "can_use_all_payments": True,
            "full_access": True,
            "message": f"Licencia vencida hace {days_expired} días. Por favor renueva.",
        }

    if days_expired <= settings.DEGRADED_PERIOD_DAYS:
        return {
            "status": "degraded",
            "days_remaining": -(days_expired),
            "can_use_reports": False,
            "can_use_all_payments": True,
            "full_access": False,
            "message": "Licencia vencida. Reportes desactivados. Renueva para recuperar acceso completo.",
        }

    # Bloqueado — solo efectivo
    return {
        "status": "blocked",
        "days_remaining": -(days_expired),
        "can_use_reports": False,
        "can_use_all_payments": False,
        "full_access": False,
        "message": "Licencia bloqueada. Solo ventas en efectivo. Renueva tu licencia.",
    }


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/validate", response_model=LicenseStatus)
def validate_license(req: ValidateRequest, db: Session = Depends(get_db)):
    """
    Llamado por la app PYFIX al iniciar.
    Verifica la licencia y actualiza last_seen_at de la activación.
    """
    tenant = db.query(Tenant).filter(
        Tenant.license_key == req.license_key.upper().strip(),
        Tenant.is_active == True,
    ).first()

    if not tenant:
        raise HTTPException(404, "Licencia no encontrada o desactivada")

    # Actualizar last_seen_at de esta activación si existe
    activation = db.query(Activation).filter(
        Activation.tenant_id == tenant.id,
        Activation.hardware_id == req.hardware_id,
        Activation.is_active == True,
    ).first()

    if activation:
        activation.last_seen_at = datetime.now(timezone.utc)
        db.commit()

    status_data = _compute_status(tenant)

    return LicenseStatus(
        valid=True,
        plan=tenant.plan,
        business_name=tenant.business_name,
        owner_name=tenant.owner_name,
        **status_data,
    )


@router.post("/activate", response_model=ActivateResponse)
def activate_license(req: ActivateRequest, db: Session = Depends(get_db)):
    """
    Registra un nuevo PC para esta licencia.
    Respeta el límite de activaciones según el plan.
    """
    tenant = db.query(Tenant).filter(
        Tenant.license_key == req.license_key.upper().strip(),
        Tenant.is_active == True,
    ).first()

    if not tenant:
        raise HTTPException(404, "Licencia no encontrada")

    # Verificar si ya está activado este hardware
    existing = db.query(Activation).filter(
        Activation.tenant_id == tenant.id,
        Activation.hardware_id == req.hardware_id,
        Activation.is_active == True,
    ).first()

    if existing:
        existing.last_seen_at = datetime.now(timezone.utc)
        if req.hostname:
            existing.hostname = req.hostname
        db.commit()
        return ActivateResponse(activated=True, message="Dispositivo ya registrado. Acceso concedido.")

    # Contar activaciones activas
    active_count = db.query(Activation).filter(
        Activation.tenant_id == tenant.id,
        Activation.is_active == True,
    ).count()

    # Límite según plan
    limits = {
        "trial": settings.MAX_ACTIVATIONS_TRIAL,
        "basic": settings.MAX_ACTIVATIONS_BASIC,
        "pro":   settings.MAX_ACTIVATIONS_PRO,
    }
    max_allowed = limits.get(tenant.plan, 1)

    if active_count >= max_allowed:
        raise HTTPException(
            403,
            f"Límite de {max_allowed} dispositivo(s) alcanzado para el plan '{tenant.plan}'. "
            "Desactiva un dispositivo o mejora tu plan."
        )

    # Crear nueva activación
    activation = Activation(
        tenant_id=tenant.id,
        hardware_id=req.hardware_id,
        hostname=req.hostname,
        is_active=True,
    )
    db.add(activation)
    db.commit()

    return ActivateResponse(
        activated=True,
        message=f"Dispositivo activado correctamente. ({active_count + 1}/{max_allowed} dispositivos usados)"
    )


@router.get("/status/{license_key}", response_model=LicenseStatus)
def license_status(license_key: str, db: Session = Depends(get_db)):
    """Estado completo de una licencia (para panel web del tendero)."""
    tenant = db.query(Tenant).filter(
        Tenant.license_key == license_key.upper().strip(),
    ).first()

    if not tenant:
        raise HTTPException(404, "Licencia no encontrada")

    status_data = _compute_status(tenant)

    return LicenseStatus(
        valid=tenant.is_active,
        plan=tenant.plan,
        business_name=tenant.business_name,
        owner_name=tenant.owner_name,
        **status_data,
    )
