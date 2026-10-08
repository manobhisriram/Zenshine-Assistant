"""Fixed-window rate limiting backed by Redis, with an in-process fallback for single-node dev."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from app.core import metrics
from app.core.errors import RateLimited
from app.core.logging import get_logger

log = get_logger("ratelimit")


@dataclass(slots=True)
class LimitResult:
    allowed: bool
    remaining: int
    retry_after: int


class Counter(Protocol):
    async def incr(self, key: str, window: int) -> int: ...


class MemoryCounter:
    """Process-local counter. Not shared across replicas: use Redis in any multi-instance deployment."""

    def __init__(self, max_keys: int = 50_000) -> None:
        self._data: dict[str, tuple[int, float]] = {}
        self._max = max_keys

    async def incr(self, key: str, window: int) -> int:
        now = time.monotonic()
        count, expires = self._data.get(key, (0, 0.0))
        if expires <= now:
            count, expires = 0, now + window
        count += 1
        self._data[key] = (count, expires)
        if len(self._data) > self._max:
            self._data = {k: v for k, v in self._data.items() if v[1] > now}
        return count


class RedisCounter:
    def __init__(self, redis) -> None:  # redis.asyncio.Redis
        self._redis = redis

    async def incr(self, key: str, window: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window, nx=True)
            count, _ = await pipe.execute()
        return int(count)


class RateLimiter:
    def __init__(self, counter: Counter, prefix: str = "rl") -> None:
        self._counter = counter
        self._prefix = prefix

    async def hit(self, scope: str, identity: str, limit: int, window: int) -> LimitResult:
        bucket = int(time.time() // window)
        key = f"{self._prefix}:{scope}:{identity}:{bucket}"
        try:
            count = await self._counter.incr(key, window + 1)
        except Exception as exc:  # fail open: availability beats strictness, but make noise
            log.error("ratelimit_backend_error", error_type=type(exc).__name__)
            return LimitResult(True, limit, 0)
        remaining = max(0, limit - count)
        retry_after = window - int(time.time() % window)
        return LimitResult(count <= limit, remaining, retry_after)

    async def enforce(self, scope: str, identity: str, limit: int, window: int) -> LimitResult:
        result = await self.hit(scope, identity, limit, window)
        if not result.allowed:
            metrics.RATE_LIMITED.labels(scope=scope).inc()
            raise RateLimited(headers={"Retry-After": str(result.retry_after)})
        return result
