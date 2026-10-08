from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import Container, chat_guard, container, identity_of, resolve_tenant
from app.api.schemas import ChatRequest, ChatResponse, FeedbackRequest
from app.core import metrics
from app.core.errors import AppError, NotFound
from app.core.logging import get_logger
from app.core.metrics import emit_emf
from app.services.agent import SAFE_ERROR_TEXT, TurnResult
from app.services.guardrails import looks_like_injection, sanitize
from app.services.tools import ToolContext

router = APIRouter(prefix="/v1", tags=["chat"])
log = get_logger("chat")

SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def _admit(request: Request, body: ChatRequest, c: Container) -> tuple[str, str, str]:
    """Rate limits + session id. Returns (session_id, identity, cleaned_message)."""
    identity = identity_of(request, c)
    s = c.settings
    await c.limiter.enforce("ip_min", identity, s.rate_limit_ip_per_minute, 60)
    await c.limiter.enforce("ip_day", identity, s.rate_limit_ip_per_day, 86400)
    session_id = body.session_id or uuid.uuid4().hex
    await c.limiter.enforce("sess_min", session_id, s.rate_limit_session_per_minute, 60)
    message = sanitize(body.message, s.max_message_chars)
    if not message:
        from app.core.errors import BadRequest

        raise BadRequest("Message is empty.")
    return session_id, identity, message


async def _run_turn(
    c: Container, tenant_id: str, session_id: str, identity: str, message: str, result: TurnResult
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    tenant = resolve_tenant(c, tenant_id)
    assert c.retriever and c.agent
    if looks_like_injection(message):
        log.warning("prompt_injection_suspected", session=session_id[:8])
    history = await c.sessions.load(tenant.id, session_id)
    retrieval = await c.retriever.retrieve(tenant.id, message)
    yield "retrieval", {"passages": len(retrieval.matches), "degraded": retrieval.degraded}
    ctx = ToolContext(tenant=tenant, session_id=session_id, identity=identity, leads=c.leads, limiter=c.limiter)
    async for item in c.agent.stream(
        tenant=tenant, history=history, user_message=message, retrieval=retrieval, tool_ctx=ctx, result=result
    ):
        yield item
    if result.text.strip():
        await c.sessions.append(
            tenant.id, session_id, [{"role": "user", "content": message}, {"role": "assistant", "content": result.text}]
        )
    sources = [
        {"id": m.id, "score": round(m.score, 3), "question": m.metadata.get("question") or m.text[:120]}
        for m in retrieval.matches
    ]
    yield "sources", {"sources": sources}


def _emit_turn_metrics(c: Container, tenant: str, r: TurnResult, total_ms: float) -> None:
    m: dict[str, tuple[float, str]] = {
        "ChatTurns": (1, "Count"),
        "ChatErrors": (1 if r.error else 0, "Count"),
        "FallbackUsed": (1 if r.fallback_used else 0, "Count"),
        "ChatLatencyMs": (total_ms, "Milliseconds"),
        "InputTokens": (r.input_tokens, "Count"),
        "OutputTokens": (r.output_tokens, "Count"),
        "CacheReadTokens": (r.cache_read_tokens, "Count"),
    }
    if r.ttft_ms is not None:
        m["TimeToFirstTokenMs"] = (r.ttft_ms, "Milliseconds")
    emit_emf(c.settings.emf_namespace, m, {"Tenant": tenant}, c.settings.emf_enabled)


@router.post("/chat/stream", dependencies=[Depends(chat_guard)])
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    c = container(request)
    tenant = resolve_tenant(c, body.tenant)
    session_id, identity, message = await _admit(request, body, c)
    message_id = uuid.uuid4().hex
    request_id = request.state.request_id

    async def gen() -> AsyncIterator[bytes]:
        structlog.contextvars.bind_contextvars(request_id=request_id)
        metrics.ACTIVE_STREAMS.inc()
        started = time.perf_counter()
        result = TurnResult()
        try:
            yield b": open\n\n"
            yield sse("meta", {"session_id": session_id, "message_id": message_id, "request_id": request_id})
            sources: dict[str, Any] = {}
            async for event, data in _run_turn(c, tenant.id, session_id, identity, message, result):
                if event == "sources":
                    sources = data
                    continue
                if event == "retrieval":
                    continue
                yield sse(event, data)
            yield sse("sources", sources or {"sources": []})
            yield sse(
                "done",
                {
                    "message_id": message_id,
                    "model": result.model,
                    "tools_used": result.tools_used,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                },
            )
        except AppError as exc:
            result.error = True
            yield sse("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:
            result.error = True
            log.error("chat_stream_failed", error_type=type(exc).__name__, exc_info=True)
            yield sse("error", {"code": "upstream_error", "message": SAFE_ERROR_TEXT})
        finally:
            metrics.ACTIVE_STREAMS.dec()
            _emit_turn_metrics(c, tenant.id, result, (time.perf_counter() - started) * 1000)
            log.info(
                "chat_turn",
                session=session_id[:8],
                tenant=tenant.id,
                model=result.model,
                in_tokens=result.input_tokens,
                out_tokens=result.output_tokens,
                cache_read=result.cache_read_tokens,
                tools=result.tools_used,
                fallback=result.fallback_used,
                chars=len(result.text),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(chat_guard)])
async def chat(request: Request, body: ChatRequest) -> JSONResponse:
    c = container(request)
    tenant = resolve_tenant(c, body.tenant)
    session_id, identity, message = await _admit(request, body, c)
    result = TurnResult()
    sources: list[dict] = []
    started = time.perf_counter()
    try:
        async for event, data in _run_turn(c, tenant.id, session_id, identity, message, result):
            if event == "sources":
                sources = data["sources"]
    except AppError:
        result.error = True
        _emit_turn_metrics(c, tenant.id, result, (time.perf_counter() - started) * 1000)
        raise
    except Exception as exc:
        result.error = True
        _emit_turn_metrics(c, tenant.id, result, (time.perf_counter() - started) * 1000)
        log.error("chat_failed", error_type=type(exc).__name__, exc_info=True)
        from app.core.errors import UpstreamUnavailable

        raise UpstreamUnavailable(SAFE_ERROR_TEXT) from exc
    _emit_turn_metrics(c, tenant.id, result, (time.perf_counter() - started) * 1000)
    return JSONResponse(
        ChatResponse(
            session_id=session_id,
            message_id=uuid.uuid4().hex,
            answer=result.text.strip(),
            sources=sources,
            model=result.model,
            tools_used=result.tools_used,
        ).model_dump()
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(request: Request, session_id: str, tenant: str | None = None) -> None:
    from app.api.schemas import SESSION_RE

    c = container(request)
    t = resolve_tenant(c, tenant)
    if not SESSION_RE.match(session_id):
        raise NotFound()
    await c.sessions.clear(t.id, session_id)


@router.post("/feedback", status_code=202)
async def feedback(request: Request, body: FeedbackRequest) -> dict[str, str]:
    c = container(request)
    await c.limiter.enforce("feedback", identity_of(request, c), 30, 60)
    metrics.FEEDBACK.labels(rating=body.rating).inc()
    log.info(
        "feedback", session=body.session_id[:8], message_id=body.message_id, rating=body.rating, has_comment=bool(body.comment)
    )
    return {"status": "accepted"}


@router.get("/config")
async def public_config(request: Request, tenant: str | None = None) -> dict[str, Any]:
    c = container(request)
    t = resolve_tenant(c, tenant)
    return {
        "tenant": t.id,
        "brand": {"name": t.brand.name, "tagline": t.brand.tagline, "city": t.brand.city},
        "locale": t.locale.model_dump(),
        "contact": {"phone": t.contact.phone, "email": t.contact.email, "hours": t.contact.hours},
        "ui": t.ui.model_dump(),
        "limits": {"max_message_chars": c.settings.max_message_chars},
    }
