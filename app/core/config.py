from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str
    database_sync_url: str

    # Redis
    redis_url: str

    # Kafka
    kafka_bootstrap_servers: str
    kafka_topic_raw_transactions: str = "raw-transactions"
    kafka_topic_upi_events: str = "upi-events"
    kafka_topic_alerts: str = "compliance-alerts"
    kafka_topic_dlq: str = "dlq-transactions"

    # OpenAI
    openai_api_key: str

    # Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # App
    app_env: str = "development"
    app_debug: bool = True

    # Celery
    celery_broker_url: str
    celery_result_backend: str

    class Config:
        env_file = ".env"
        case_sensitive = False


# This is the single settings object used everywhere in the app
settings = Settings()