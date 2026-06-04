import logging
import time

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def check_rate_limit(
    tenant_id: str,
    endpoint: str,
    limit: int = 100,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """
    Sliding window rate limiter using Redis sorted sets.

    Each request is recorded as a member of a sorted set with its
    Unix timestamp as the score. Old entries (outside the window) are
    pruned on every request, and the remaining count is the number of
    requests in the current window.

    Returns:
        (allowed: bool, current_count: int)

    If Redis is unavailable, fails open (allows the request) to prevent
    a Redis outage from taking down the entire API.

    Covers edge case #79: per-tenant request quotas.
    """
    key = f"ratelimit:{tenant_id}:{endpoint}"
    now = time.time()
    window_start = now - window_seconds

    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)      # remove old entries
        pipe.zadd(key, {str(now): now})                   # add current request
        pipe.zcard(key)                                    # count in window
        pipe.expire(key, window_seconds)                   # auto-cleanup
        results = await pipe.execute()

        count = int(results[2])
        return count <= limit, count

    except Exception as e:
        logger.warning(f"Rate limiter Redis error (failing open): {e}")
        return True, 0  # fail open — don't block requests if Redis is down
