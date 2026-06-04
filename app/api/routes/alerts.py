import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.sar_generator import generate_sar
from app.db.models import Alert, SARReport
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Alerts & SAR"])


# ── Response schemas ──────────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    id: str
    severity: str
    rule_triggered: str | None
    is_resolved: bool
    transaction_id: str | None
    created_at: str

    model_config = {"from_attributes": True}


class SARResponse(BaseModel):
    id: str
    alert_id: str | None
    narrative: str | None
    pdf_path: str | None
    filed_with_fiu: bool
    created_at: str

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/alerts",
    summary="List all unresolved alerts",
)
async def list_alerts(
    resolved: bool = False,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Alert)
        .where(Alert.is_resolved == resolved)
        .order_by(Alert.created_at.desc())
        .limit(50)
    )
    alerts = result.scalars().all()

    return [
        {
            "id":             str(a.id),
            "severity":       a.severity.value,
            "rule_triggered": a.rule_triggered,
            "is_resolved":    a.is_resolved,
            "transaction_id": str(a.transaction_id) if a.transaction_id else None,
            "created_at":     str(a.created_at),
        }
        for a in alerts
    ]


@router.get(
    "/alerts/{alert_id}",
    summary="Get a specific alert",
)
async def get_alert(alert_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return {
        "id":             str(alert.id),
        "severity":       alert.severity.value,
        "rule_triggered": alert.rule_triggered,
        "is_resolved":    alert.is_resolved,
        "transaction_id": str(alert.transaction_id) if alert.transaction_id else None,
        "created_at":     str(alert.created_at),
    }


@router.post(
    "/alerts/{alert_id}/generate-sar",
    status_code=status.HTTP_201_CREATED,
    summary="Generate a SAR report for an alert using GPT-4o",
)
async def trigger_sar_generation(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Triggers the full SAR generation pipeline:
    1. Loads the alert and transaction from the DB
    2. Searches for similar past cases via pgvector
    3. Calls GPT-4o (or GPT-4o-mini for lower severity) via LangChain
    4. Saves the narrative to the DB
    5. Renders a PDF
    6. Returns the SAR report

    Idempotent — calling this twice for the same alert returns the existing SAR.
    """
    try:
        sar = await generate_sar(alert_id=alert_id, session=db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"SAR generation failed for alert {alert_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"SAR generation failed: {str(e)}",
        )

    return {
        "id":           str(sar.id),
        "alert_id":     str(sar.alert_id),
        "narrative":    sar.narrative,
        "pdf_path":     sar.pdf_path,
        "filed_with_fiu": sar.filed_with_fiu,
        "created_at":   str(sar.created_at),
        "message":      "SAR generated successfully. Review and file with FIU-IND within 7 days.",
    }


@router.get(
    "/sar-reports",
    summary="List all SAR reports",
)
async def list_sar_reports(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SARReport).order_by(SARReport.created_at.desc()).limit(50)
    )
    reports = result.scalars().all()

    return [
        {
            "id":             str(r.id),
            "alert_id":       str(r.alert_id) if r.alert_id else None,
            "pdf_path":       r.pdf_path,
            "filed_with_fiu": r.filed_with_fiu,
            "created_at":     str(r.created_at),
        }
        for r in reports
    ]


@router.get(
    "/sar-reports/{sar_id}",
    summary="Get a specific SAR report with full narrative",
)
async def get_sar_report(sar_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SARReport).where(SARReport.id == sar_id))
    sar = result.scalar_one_or_none()

    if not sar:
        raise HTTPException(status_code=404, detail="SAR report not found")

    return {
        "id":             str(sar.id),
        "alert_id":       str(sar.alert_id) if sar.alert_id else None,
        "narrative":      sar.narrative,
        "pdf_path":       sar.pdf_path,
        "filed_with_fiu": sar.filed_with_fiu,
        "created_at":     str(sar.created_at),
    }


@router.get(
    "/sar-reports/{sar_id}/pdf",
    summary="Download the SAR PDF",
)
async def download_sar_pdf(sar_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SARReport).where(SARReport.id == sar_id))
    sar = result.scalar_one_or_none()

    if not sar:
        raise HTTPException(status_code=404, detail="SAR report not found")

    if not sar.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not yet generated for this SAR")

    return FileResponse(
        path=sar.pdf_path,
        media_type="application/pdf",
        filename=f"SAR_{str(sar.id)[:8].upper()}.pdf",
    )
