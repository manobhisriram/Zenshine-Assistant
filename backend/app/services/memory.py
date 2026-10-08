"""Conversation memory: Redis in production (shared across tasks), in-process fallback for local dev."""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import Protocol

from app.core.logging import get_logger

log = get_logger("memory")

Turn = dict[str, str]  # {"role": "user"|"assistant", "content": str}


class SessionStore(Protocol):
    async def load(self, tenant: str, session_id: str) -> list[Turn]: ...
    async def append(self, tenant: str, session_id: str, turns: list[Turn]) -> None: ...
    async def clear(self, tenant: str, session_id: str) -> None: ...
    async def ping(self) -> bool: ...


class MemorySessionStore:
    def __init__(self, max_turns: int, ttl: int, max_sessions: int = 20_000) -> None:
        self._max = max_turns * 2
        self._ttl = ttl
        self._max_sessions = max_sessions
        self._data: OrderedDict[str, tuple[float, list[Turn]]] = OrderedDict()

    def _key(self, tenant: str, sid: str) -> str:
        return f"{tenant}:{sid}"

    async def load(self, tenant: str, session_id: str) -> list[Turn]:
        item = self._data.get(self._key(tenant, session_id))
        if not item or item[0] < time.time():
            return []
        return list(item[1])

    async def append(self, tenant: str, session_id: str, turns: list[Turn]) -> None:
        key = self._key(tenant, session_id)
        history = (await self.load(tenant, session_id)) + turns
        self._data[key] = (time.time() + self._ttl, history[-self._max :])
        self._data.move_to_end(key)
        while len(self._data) > self._max_sessions:
            self._data.popitem(last=False)

    async def clear(self, tenant: str, session_id: str) -> None:
        self._data.pop(self._key(tenant, session_id), None)

    async def ping(self) -> bool:
        return True


class RedisSessionStore:
    def __init__(self, redis, max_turns: int, ttl: int) -> None:  # redis.asyncio.Redis
        self._r = redis
        self._max = max_turns * 2
        self._ttl = ttl

    def _key(self, tenant: str, sid: str) -> str:
        return f"sess:{tenant}:{sid}"

    async def load(self, tenant: str, session_id: str) -> list[Turn]:
        try:
            raw = await self._r.lrange(self._key(tenant, session_id), 0, -1)
        except Exception as exc:
            log.error("session_load_failed", error_type=type(exc).__name__)
            return []
        return [json.loads(x) for x in raw]

    async def append(self, tenant: str, session_id: str, turns: list[Turn]) -> None:
        key = self._key(tenant, session_id)
        try:
            pipe = self._r.pipeline(transaction=True)
            pipe.rpush(key, *[json.dumps(t, ensure_ascii=False) for t in turns])
            pipe.ltrim(key, -self._max, -1)
            pipe.expire(key, self._ttl)
            await pipe.execute()
        except Exception as exc:  # losing history is better than failing the user's turn
            log.error("session_append_failed", error_type=type(exc).__name__)

    async def clear(self, tenant: str, session_id: str) -> None:
        try:
            await self._r.delete(self._key(tenant, session_id))
        except Exception as exc:
            log.error("session_clear_failed", error_type=type(exc).__name__)

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:
            return False
