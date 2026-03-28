"""
Registro y login de tenderos.
"""
import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from database import get_db
from models import Tenant
from config import settings
from deps import create_token

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Helpers ───────────────────────────────────────────────────

def _generate_license_key() -> str:
    """Genera PYFIX-XXXX-XXXX-XXXX con caracteres alfanuméricos en mayúscula."""
    chars = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    return "PYFIX-" + "-".join(parts)


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── Schemas ───────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    business_name: str
    owner_name: str
    email: str
    phone: str | None = None
    city: str | None = None
    password: str


class RegisterResponse(BaseModel):
    tenant_id: str
    license_key: str
    business_name: str
    plan: str
    trial_ends_at: datetime
    message: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    license_key: str
    business_name: str
    plan: str
    trial_ends_at: datetime | None
    paid_until: datetime | None


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    # Verificar que el email no exista
    existing = db.query(Tenant).filter(Tenant.email == req.email.lower().strip()).first()
    if existing:
        raise HTTPException(400, "Ya existe una cuenta con ese correo electrónico")

    trial_ends = datetime.now(timezone.utc) + timedelta(days=settings.TRIAL_DURATION_DAYS)

    tenant = Tenant(
        business_name=req.business_name.strip(),
        owner_name=req.owner_name.strip(),
        email=req.email.lower().strip(),
        phone=req.phone,
        city=req.city,
        password_hash=_hash_password(req.password),
        license_key=_generate_license_key(),
        plan="trial",
        trial_ends_at=trial_ends,
        is_active=True,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    return RegisterResponse(
        tenant_id=str(tenant.id),
        license_key=tenant.license_key,
        business_name=tenant.business_name,
        plan=tenant.plan,
        trial_ends_at=tenant.trial_ends_at,
        message=f"¡Bienvenido! Tu período de prueba de {settings.TRIAL_DURATION_DAYS} días está activo.",
    )


class RecoverRequest(BaseModel):
    email: str
    phone: str  # Segundo factor — teléfono registrado (10 dígitos)


class RecoverResponse(BaseModel):
    license_key: str
    business_name: str
    owner_name: str


# Registro simple en memoria para rate-limiting (máx 5 intentos por IP cada 10 min)
import time
from collections import defaultdict
_recover_attempts: dict = defaultdict(list)
_RECOVER_MAX = 5
_RECOVER_WINDOW = 600  # segundos


@router.post("/recover", response_model=RecoverResponse)
def recover_license(
    req: RecoverRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Recupera la clave de licencia.
    Requiere TANTO el correo como el teléfono registrados (verificación doble).
    Rate-limited: máx 5 intentos por IP cada 10 minutos.
    """

    # ── Rate limiting por IP ──────────────────────────────────────────────────
    client_ip = getattr(request, "client", None)
    ip = client_ip.host if client_ip else "unknown"
    now = time.time()
    # Limpiar intentos expirados
    _recover_attempts[ip] = [t for t in _recover_attempts[ip] if now - t < _RECOVER_WINDOW]
    if len(_recover_attempts[ip]) >= _RECOVER_MAX:
        raise HTTPException(
            429,
            "Demasiados intentos. Espera 10 minutos antes de intentar de nuevo."
        )
    _recover_attempts[ip].append(now)

    # ── Validar formato del teléfono ──────────────────────────────────────────
    phone_clean = req.phone.strip().replace(" ", "").replace("-", "")
    if not phone_clean.isdigit() or len(phone_clean) != 10:
        raise HTTPException(400, "El número de teléfono debe tener exactamente 10 dígitos.")

    # ── Buscar cuenta con email Y teléfono ───────────────────────────────────
    tenant = db.query(Tenant).filter(
        Tenant.email == req.email.lower().strip(),
        Tenant.is_active == True,
    ).first()

    # Mensaje genérico para no revelar si el email existe o no
    _err = ("Los datos ingresados no coinciden con ninguna cuenta activa. "
            "Verifica el correo y el teléfono con que te registraste.")

    if not tenant:
        raise HTTPException(404, _err)

    # Verificar que el teléfono coincida
    stored_phone = (tenant.phone or "").strip().replace(" ", "").replace("-", "")
    if stored_phone != phone_clean:
        raise HTTPException(404, _err)

    return RecoverResponse(
        license_key=tenant.license_key,
        business_name=tenant.business_name,
        owner_name=tenant.owner_name,
    )


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(
        Tenant.email == req.email.lower().strip(),
        Tenant.is_active == True,
    ).first()

    if not tenant or not _check_password(req.password, tenant.password_hash):
        raise HTTPException(401, "Correo o contraseña incorrectos")

    token = create_token({"sub": str(tenant.id), "email": tenant.email})

    return LoginResponse(
        access_token=token,
        tenant_id=str(tenant.id),
        license_key=tenant.license_key,
        business_name=tenant.business_name,
        plan=tenant.plan,
        trial_ends_at=tenant.trial_ends_at,
        paid_until=tenant.paid_until,
    )
