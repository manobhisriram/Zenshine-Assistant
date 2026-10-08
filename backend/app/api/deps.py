"""Application container and request-scoped dependencies."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import Header, Request

from app.config import Settings
from app.core.errors import BadRequest, Unauthorized, UpstreamUnavailable
from app.core.ratelimit import RateLimiter
from app.core.security import client_ip, constant_time_in, hash_identity, require_secret
from app.services.agent import ChatAgent
from app.services.leads import LeadService
from app.services.memory import SessionStore
from app.services.rag import Retriever
from app.services.tenants import Tenant, TenantRegistry
from app.services.vectorstore import VectorStore


@dataclass
class Container:
    settings: Settings
    registry: TenantRegistry
    limiter: RateLimiter
    sessions: SessionStore
    leads: LeadService
    store: VectorStore | None = None
    retriever: Retriever | None = None
    agent: ChatAgent | None = None
    redis: Any = None
    ingest_status: dict[str, Any] = field(default_factory=lambda: {"state": "idle"})
    ingest_lock: Any = None
    ready_cache: tuple[float, dict[str, Any]] | None = None
    background: set = field(default_factory=set)


def container(request: Request) -> Container:
    return request.app.state.container


def resolve_tenant(c: Container, tenant_id: str | None) -> Tenant:
    tenant = c.registry.get(tenant_id or c.settings.default_tenant)
    if tenant is None:
        raise BadRequest("Unknown tenant.")
    return tenant


def identity_of(request: Request, c: Container) -> str:
    return hash_identity(client_ip(request, c.settings.trusted_proxy_hops))


async def chat_guard(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    c = container(request)
    if c.settings.require_api_key and (not x_api_key or not constant_time_in(x_api_key, c.settings.api_key_list)):
        raise Unauthorized()
    if c.agent is None or c.retriever is None:
        raise UpstreamUnavailable("The assistant is not configured yet.")


async def admin_guard(request: Request, x_admin_key: str | None = Header(default=None)) -> None:
    c = container(request)
    await c.limiter.enforce("admin", identity_of(request, c), 20, 60)
    require_secret(x_admin_key, [c.settings.admin_api_key] if c.settings.admin_api_key else [])


def now() -> float:
    return time.time()
