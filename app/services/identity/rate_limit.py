"""Fixed-window login rate limiting in Redis. Fails closed when Redis is unavailable."""

from __future__ import annotations

import hashlib

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import RateLimitedError, ServiceUnavailableError
from app.core.logging import get_logger

WINDOW_SECONDS = 60
logger = get_logger(__name__)


def login_keys(ip: str | None, email: str) -> list[str]:
    email_digest = hashlib.sha256(email.encode("utf-8")).hexdigest()
    keys = [f"rl:login:email:{email_digest}"]
    if ip:
        keys.append(f"rl:login:ip:{ip}")
    return keys


async def check_login_rate(redis: Redis, ip: str | None, email: str, limit: int) -> None:
    try:
        async with redis.pipeline(transaction=True) as pipe:
            keys = login_keys(ip, email)
            for key in keys:
                pipe.incr(key)
                pipe.expire(key, WINDOW_SECONDS, nx=True)
            results = await pipe.execute()
            counts = [int(results[i * 2]) for i in range(len(keys))]
            if max(counts) > limit:
                ttls = [int(await redis.ttl(k)) for k in keys]
                ttl = max(ttls)
                raise RateLimitedError(
                    "Too many login attempts. Try again later.",
                    headers={"Retry-After": str(max(ttl, 1))},
                )
    except RedisError as exc:
        logger.error("rate_limiter_unavailable", extra={"error": type(exc).__name__})
        raise ServiceUnavailableError("Login is temporarily unavailable.") from exc
