"""Request context, security headers, client IP resolution and credential checks."""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid

import structlog
from fastapi import Request
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics
from app.core.errors import Unauthorized
from app.core.logging import get_logger

log = get_logger("http")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
}


def client_ip(request: Request, trusted_hops: int) -> str:
    """Resolve the client IP from X-Forwarded-For given the number of trusted proxies in front."""
    xff = request.headers.get("x-forwarded-for", "")
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if parts and trusted_hops > 0:
        return parts[-trusted_hops] if len(parts) >= trusted_hops else parts[0]
    return request.client.host if request.client else "unknown"


def hash_identity(value: str) -> str:
    """Stable, non-reversible identifier so raw IPs never end up in cache keys or logs."""
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def constant_time_in(candidate: str, secrets_list: list[str]) -> bool:
    ok = False
    for secret in secrets_list:
        ok |= hmac.compare_digest(candidate.encode(), secret.encode())
    return ok


def require_secret(provided: str | None, expected: list[str]) -> None:
    if not provided or not expected or not constant_time_in(provided, expected):
        raise Unauthorized()


class RequestContextMiddleware:
    """Pure-ASGI middleware (safe for SSE streaming): request id, body-size guard, security headers, metrics."""

    def __init__(self, app: ASGIApp, max_body: int) -> None:
        self.app = app
        self._max_body = max_body

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        raw_rid = headers.get("x-request-id", "")
        rid = raw_rid if raw_rid and len(raw_rid) <= 64 and all(c.isalnum() or c in "-_" for c in raw_rid) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)

        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > self._max_body:
            response = JSONResponse(
                {"error": {"code": "payload_too_large", "message": "Request body too large.", "request_id": rid}},
                status_code=413,
            )
            await response(scope, receive, send)
            return

        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                out = MutableHeaders(scope=message)
                out["X-Request-ID"] = rid
                for key, value in SECURITY_HEADERS.items():
                    if key not in out:
                        out[key] = value
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            route = getattr(scope.get("route"), "path", "unmatched")
            metrics.HTTP_REQUESTS.labels(scope["method"], route, str(status)).inc()
            metrics.HTTP_LATENCY.labels(route).observe(elapsed)
            if route not in ("/healthz", "/readyz", "/metrics"):
                log.info("http_request", method=scope["method"], path=route, status=status, duration_ms=round(elapsed * 1000, 1))
