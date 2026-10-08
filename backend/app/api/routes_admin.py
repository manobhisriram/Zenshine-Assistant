from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.api.deps import Container, admin_guard, container, resolve_tenant
from app.api.schemas import IngestRequest
from app.core.errors import BadRequest, UpstreamUnavailable
from app.core.logging import get_logger
from app.services.ingest import sync_tenant

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(admin_guard)])
log = get_logger("admin")


async def run_ingest(c: Container, tenant_id: str) -> dict:
    if c.store is None:
        raise UpstreamUnavailable("Vector store is not configured.")
    if c.ingest_lock is None:
        c.ingest_lock = asyncio.Lock()
    if c.ingest_lock.locked():
        raise BadRequest("An ingest is already running.")
    async with c.ingest_lock:
        c.ingest_status = {"state": "running", "tenant": tenant_id}
        try:
            report = await sync_tenant(c.store, Path(c.settings.knowledge_dir), tenant_id)
        except Exception as exc:
            c.ingest_status = {"state": "failed", "tenant": tenant_id, "error": type(exc).__name__}
            log.error("ingest_failed", error_type=type(exc).__name__, exc_info=True)
            raise
        c.ingest_status = {"state": "done", "tenant": tenant_id, "report": report.as_dict()}
        c.ready_cache = None
        return report.as_dict()


@router.post("/ingest")
async def ingest(request: Request, body: IngestRequest | None = None) -> dict:
    c = container(request)
    tenant = resolve_tenant(c, body.tenant if body else None)
    await c.limiter.enforce("ingest", "global", c.settings.rate_limit_ingest_per_hour, 3600)
    return await run_ingest(c, tenant.id)


@router.get("/status")
async def status(request: Request) -> dict:
    c = container(request)
    count = None
    if c.store is not None:
        try:
            count = await c.store.count(resolve_tenant(c, None).id)
        except Exception:
            count = None
    return {"ingest": c.ingest_status, "tenants": c.registry.ids(), "vectors": count, "version": c.settings.app_version}
