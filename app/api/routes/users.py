import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_role
from app.core.security import hash_password
from app.db.models import User, UserRole
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["User Management"])


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.COMPLIANCE_ANALYST


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (Admin only)",
)
async def create_user(
    payload: CreateUserRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin-only endpoint to onboard a new analyst, risk manager, or auditor.
    The new user is automatically assigned to the same tenant as the admin.

    Covers edge case #39 — system always has at least one admin per tenant.
    """
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with email {payload.email} already exists",
        )

    # Prevent creating a second ADMIN unless explicitly needed
    # (keeps privilege escalation surface small)
    if payload.role == UserRole.ADMIN:
        admin_count = await db.execute(
            select(User).where(
                User.tenant_id == current_user.tenant_id,
                User.role == UserRole.ADMIN,
                User.is_active == True,
            )
        )
        if len(admin_count.scalars().all()) >= 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 2 admin accounts allowed per tenant",
            )

    user = User(
        tenant_id=current_user.tenant_id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(f"User created: {user.email} ({user.role.value}) by admin {current_user.email}")

    return {
        "id":        str(user.id),
        "email":     user.email,
        "full_name": user.full_name,
        "role":      user.role.value,
        "tenant_id": str(user.tenant_id),
    }


@router.get(
    "",
    summary="List all users in the tenant (Admin only)",
)
async def list_users(
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .where(User.tenant_id == current_user.tenant_id)
        .order_by(User.created_at.desc())
    )
    users = result.scalars().all()

    return [
        {
            "id":        str(u.id),
            "email":     u.email,
            "full_name": u.full_name,
            "role":      u.role.value,
            "is_active": u.is_active,
            "created_at": str(u.created_at),
        }
        for u in users
    ]
