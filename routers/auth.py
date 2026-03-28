"""
Registro y login de tenderos.
"""
import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
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
