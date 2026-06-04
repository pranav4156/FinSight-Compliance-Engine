from fastapi import APIRouter

from app.api.routes.alerts import router as alerts_router
from app.api.routes.transactions import router as transactions_router

api_router = APIRouter()
api_router.include_router(transactions_router)
api_router.include_router(alerts_router)
