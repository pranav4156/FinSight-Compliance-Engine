import asyncio
import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.db.models import Alert, SARReport, Transaction

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


def _render_pdf_sync(sar: SARReport, alert: Alert, txn: Transaction) -> str:
    """
    Render the SAR as a PDF using Jinja2 + WeasyPrint.
    Runs synchronously — called from asyncio via run_in_executor.

    WeasyPrint converts HTML+CSS to a pixel-perfect PDF.
    The Jinja2 template (sar_report.html) handles all the formatting.
    """
    REPORTS_DIR.mkdir(exist_ok=True)

    rules_list = [r.strip() for r in (alert.rule_triggered or "anomaly_detection").split("|")]

    template_context = {
        "report_id":       f"SAR-{str(sar.id)[:8].upper()}",
        "alert_id":        str(alert.id)[:8].upper(),
        "date_filed":      datetime.utcnow().strftime("%d %B %Y, %H:%M UTC"),
        "analyst_id":      str(sar.created_by)[:8].upper() if sar.created_by else "SYSTEM",
        "severity":        alert.severity.value.upper(),
        "rules_list":      rules_list,
        "anomaly_score":   float(txn.anomaly_score or 0),
        "transaction_ref": txn.transaction_ref,
        "sender_account":  txn.sender_account,
        "receiver_account":txn.receiver_account,
        "amount":          f"{txn.amount:,}",
        "channel":         txn.channel or "UNKNOWN",
        "transaction_time":txn.created_at.strftime("%Y-%m-%d %H:%M UTC") if txn.created_at else "unknown",
        "narrative":       sar.narrative or "",
    }

    template = _jinja_env.get_template("sar_report.html")
    html_content = template.render(**template_context)

    filename = f"SAR_{str(sar.id)[:8].upper()}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf_path = REPORTS_DIR / filename

    from weasyprint import HTML
    HTML(string=html_content).write_pdf(str(pdf_path))

    logger.info(f"PDF rendered → {pdf_path}  ({pdf_path.stat().st_size / 1024:.1f} KB)")
    return str(pdf_path)


async def render_sar_pdf(sar: SARReport, alert: Alert, txn: Transaction) -> str:
    """
    Async wrapper for PDF rendering.
    WeasyPrint is synchronous so we run it in a thread pool executor
    to avoid blocking the FastAPI event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _render_pdf_sync, sar, alert, txn)
