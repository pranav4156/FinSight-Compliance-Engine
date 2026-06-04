from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: UUID, role: str, tenant_id: UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":       str(user_id),
        "role":      role,
        "tenant_id": str(tenant_id),
        "exp":       now + timedelta(minutes=settings.access_token_expire_minutes),
        "iat":       now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """
    Decode and verify a JWT. Raises ValueError on any failure
    (expired, tampered, wrong signature).
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}")
