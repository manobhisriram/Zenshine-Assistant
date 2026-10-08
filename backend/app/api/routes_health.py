from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Header, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.deps import Container, container
from app.core.errors import Unauthorized
from app.core.metrics import REGISTRY
from app.core.security import constant_time_in

router = APIRouter(tags=["ops"])
READY_TTL = 10.0


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    """Process is up. Never touches dependencies, so a dependency outage can't cause restart loops."""
    return {"status": "ok"}


async def _probe(c: Container) -> dict[str, Any]:
    checks: dict[str, Any] = {}

    async def timed(name: str, coro) -> None:
        try:
            checks[name] = bool(await asyncio.wait_for(coro, 3))
        except Exception:
            checks[name] = False

    jobs = [timed("sessions", c.sessions.ping()), timed("leads", c.leads.ping())]
    if c.store is not None:
        jobs.append(timed("vector_store", c.store.ping()))
    await asyncio.gather(*jobs)
    checks["llm_configured"] = c.agent is not None
    checks["vector_store_configured"] = c.store is not None
    return checks


@router.get("/readyz")
async def readiness(request: Request, response: Response) -> dict[str, Any]:
    c = container(request)
    if c.ready_cache and time.monotonic() - c.ready_cache[0] < READY_TTL:
        body = c.ready_cache[1]
    else:
        checks = await _probe(c)
        body = {
            "status": "ready" if all(checks.values()) else "degraded",
            "checks": checks,
            "version": c.settings.app_version,
            "ingest": c.ingest_status.get("state"),
        }
        c.ready_cache = (time.monotonic(), body)
    if body["status"] != "ready":
        response.status_code = 503
    return body


@router.get("/metrics", include_in_schema=False)
async def prometheus(request: Request, authorization: str | None = Header(default=None)) -> Response:
    c = container(request)
    token = c.settings.metrics_token
    if token:
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not supplied or not constant_time_in(supplied, [token]):
            raise Unauthorized()
    elif c.settings.is_production:
        raise Unauthorized()
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
