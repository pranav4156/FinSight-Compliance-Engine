from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(
    title="FinSight Compliance Engine",
    description="Real-time AML compliance and fraud detection for Indian fintech",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.app_env,
        "service": "finsight-compliance-engine",
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "message": "FinSight API is running. Visit /docs for the API explorer."
    }