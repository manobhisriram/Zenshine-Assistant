"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_admin, routes_chat, routes_health
from app.api.deps import Container
from app.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import Counter, MemoryCounter, RateLimiter, RedisCounter
from app.core.security import RequestContextMiddleware
from app.core.telemetry import setup_tracing
from app.services.agent import ChatAgent, build_llm_client
from app.services.leads import build_lead_service
from app.services.memory import MemorySessionStore, RedisSessionStore, SessionStore
from app.services.rag import Retriever
from app.services.tenants import load_registry
from app.services.vectorstore import PineconeStore

log = get_logger("main")


def build_container(settings: Settings) -> Container:
    registry = load_registry(settings.tenants_dir)
    if registry.get(settings.default_tenant) is None:
        raise RuntimeError(f"DEFAULT_TENANT '{settings.default_tenant}' has no definition in {settings.tenants_dir}")

    redis = None
    counter: Counter
    sessions: SessionStore
    if settings.redis_url:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
            health_check_interval=30,
            max_connections=100,
        )
        counter = RedisCounter(redis)
        sessions = RedisSessionStore(redis, settings.history_turns, settings.session_ttl_seconds)
    else:
        if settings.is_production:
            log.warning("redis_not_configured", note="in-memory sessions/rate limits are per-task; set REDIS_URL")
        counter = MemoryCounter()
        sessions = MemorySessionStore(settings.history_turns, settings.session_ttl_seconds)

    c = Container(
        settings=settings,
        registry=registry,
        limiter=RateLimiter(counter),
        sessions=sessions,
        leads=build_lead_service(settings),
        redis=redis,
    )

    if settings.pinecone_api_key:
        c.store = PineconeStore(settings)
        c.retriever = Retriever(c.store, settings)
    else:
        log.warning("pinecone_not_configured", note="set PINECONE_API_KEY")
    if settings.anthropic_api_key:
        c.agent = ChatAgent(build_llm_client(settings), settings)
    else:
        log.warning("anthropic_not_configured", note="set ANTHROPIC_API_KEY")
    if settings.is_production and (c.agent is None or c.store is None):
        raise RuntimeError("ANTHROPIC_API_KEY and PINECONE_API_KEY are required in production")
    return c


async def _auto_ingest(c: Container) -> None:
    try:
        await routes_admin.run_ingest(c, c.settings.default_tenant)
        log.info("auto_ingest_done", **{k: v for k, v in c.ingest_status.get("report", {}).items() if isinstance(v, int)})
    except Exception as exc:
        log.error("auto_ingest_failed", error_type=type(exc).__name__)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        c = container or build_container(settings)
        app.state.container = c
        c.ingest_lock = asyncio.Lock()
        if settings.auto_ingest and c.store is not None:
            task = asyncio.create_task(_auto_ingest(c))
            c.background.add(task)
            task.add_done_callback(c.background.discard)
        log.info("startup", env=settings.app_env, version=settings.app_version, tenants=c.registry.ids())
        yield
        for task in list(c.background):
            task.cancel()
        if c.agent is not None:
            await c.agent._client.close()
        if c.redis is not None:
            await c.redis.aclose()
        log.info("shutdown")

    app = FastAPI(
        title="ZenShine Assistant API",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Admin-Key", "X-Request-ID", "Authorization"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, max_body=settings.max_request_bytes)
    install_error_handlers(app)
    app.include_router(routes_health.router)
    app.include_router(routes_chat.router)
    app.include_router(routes_admin.router)
    setup_tracing(app, settings)
    return app


def app_factory() -> FastAPI:
    """Entry point for uvicorn: ``uvicorn app.main:app_factory --factory``."""
    return create_app()
