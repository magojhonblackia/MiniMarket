"""
Dependencias compartidas — JWT para tenderos autenticados.
"""
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import Tenant

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def get_current_tenant(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Tenant:
    if not token:
        raise HTTPException(401, "No autenticado")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        tenant_id: str = payload.get("sub")
        if not tenant_id:
            raise HTTPException(401, "Token inválido")
    except JWTError:
        raise HTTPException(401, "Token inválido o expirado")

    tenant = db.get(Tenant, tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(401, "Cuenta no encontrada o desactivada")
    return tenant
