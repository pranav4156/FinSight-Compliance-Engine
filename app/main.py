import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prometheus_fastapi_instrumentator import Instrumentator

from app.api.routes import api_router
from app.core.config import settings
from app.kafka.consumer import run_consumer, stop_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — launch the Kafka consumer in a background daemon thread
    consumer_thread = threading.Thread(
        target=run_consumer,
        daemon=True,
        name="kafka-consumer",
    )
    consumer_thread.start()
    logger.info("Kafka consumer thread started")
    yield
    # Shutdown — signal the consumer loop to exit cleanly
    stop_consumer()
    logger.info("Shutdown complete")


app = FastAPI(
    title="FinSight Compliance Engine",
    description="Real-time AML compliance and fraud detection for Indian fintech",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Expose /metrics endpoint for Prometheus scraping
# Automatically instruments all routes: request count, latency, status codes
Instrumentator().instrument(app).expose(app, include_in_schema=False)


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.app_env,
        "service": "finsight-compliance-engine",
    }


@app.get("/", tags=["System"])
async def root():
    return {"message": "FinSight API is running. Visit /docs for the API explorer."}
