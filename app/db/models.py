import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Numeric, Boolean,
    DateTime, Text, ForeignKey, Enum, Index
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="tenant")
    transactions = relationship("Transaction", back_populates="tenant")


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    COMPLIANCE_ANALYST = "compliance_analyst"
    RISK_MANAGER = "risk_manager"
    AUDITOR = "auditor"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(Enum(UserRole, values_callable=lambda obj: [e.value for e in obj]), default=UserRole.COMPLIANCE_ANALYST)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="users")


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    FLAGGED = "flagged"
    CLEARED = "cleared"
    REPORTED = "reported"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    transaction_ref = Column(String(100), unique=True, nullable=False)
    sender_account = Column(String(100), nullable=False)
    receiver_account = Column(String(100), nullable=False)
    amount = Column(Numeric(precision=18, scale=2), nullable=False)
    currency = Column(String(10), default="INR")
    channel = Column(String(50))
    status = Column(Enum(TransactionStatus, values_callable=lambda obj: [e.value for e in obj]), default=TransactionStatus.PENDING)
    anomaly_score = Column(Float, default=0.0)
    is_suspicious = Column(Boolean, default=False)
    metadata_json = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="transactions")
    alert = relationship("Alert", back_populates="transaction", uselist=False)

    __table_args__ = (
        # Matches fetch_account_history's query shape (5 of 6 detection operators)
        Index("ix_transactions_sender_tenant_created", "sender_account", "tenant_id", "created_at"),
        # Matches graph_cycle_detector's tenant-wide recency query
        Index("ix_transactions_tenant_created", "tenant_id", "created_at"),
    )


class AlertSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("transactions.id"))
    rule_triggered = Column(String(255))
    severity = Column(Enum(AlertSeverity, values_callable=lambda obj: [e.value for e in obj]), default=AlertSeverity.MEDIUM)
    is_resolved = Column(Boolean, default=False)
    resolved_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    transaction = relationship("Transaction", back_populates="alert")


class SARReport(Base):
    __tablename__ = "sar_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    alert_id = Column(UUID(as_uuid=True), ForeignKey("alerts.id"))
    narrative = Column(Text)
    narrative_embedding = Column(Vector(1536), nullable=True)
    pdf_path = Column(String(500), nullable=True)
    filed_with_fiu = Column(Boolean, default=False)
    judge_score = Column(Float, nullable=True)
    judge_critique = Column(Text, nullable=True)
    judge_passed = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(UUID(as_uuid=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    action = Column(String(255), nullable=False)
    resource_type = Column(String(100))
    resource_id = Column(String(255))
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)