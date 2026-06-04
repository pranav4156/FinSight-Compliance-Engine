#!/usr/bin/env python3
"""
Seed the database with a demo tenant and admin user for local development.

Run once after applying migrations:
    python scripts/seed_admin.py

Default credentials:
    Email    : admin@finsight.dev
    Password : Admin@123
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import Tenant, User, UserRole

engine = create_engine(settings.database_sync_url)
Session = sessionmaker(bind=engine)

DEMO_TENANT_ID  = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEMO_TENANT_NAME = "FinSight Demo Tenant"
ADMIN_EMAIL      = "admin@finsight.dev"
ADMIN_PASSWORD   = "Admin@123"


def seed():
    with Session() as session:
        # Create demo tenant (upsert-style)
        existing_tenant = session.get(Tenant, DEMO_TENANT_ID)
        if not existing_tenant:
            tenant = Tenant(
                id=DEMO_TENANT_ID,
                name=DEMO_TENANT_NAME,
                is_active=True,
            )
            session.add(tenant)
            session.flush()
            print(f"Tenant created : {DEMO_TENANT_NAME}")
        else:
            print(f"Tenant exists  : {DEMO_TENANT_NAME}")

        # Create admin user
        from sqlalchemy import select
        existing_user = session.execute(
            select(User).where(User.email == ADMIN_EMAIL)
        ).scalar_one_or_none()

        if not existing_user:
            admin = User(
                tenant_id=DEMO_TENANT_ID,
                email=ADMIN_EMAIL,
                hashed_password=hash_password(ADMIN_PASSWORD),
                full_name="Demo Admin",
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin)
            session.commit()
            print(f"Admin created  : {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        else:
            print(f"Admin exists   : {ADMIN_EMAIL}")

    print()
    print("Ready. Start the server and login:")
    print(f"  POST /api/v1/auth/login")
    print(f'  {{"email": "{ADMIN_EMAIL}", "password": "{ADMIN_PASSWORD}"}}')


if __name__ == "__main__":
    seed()
