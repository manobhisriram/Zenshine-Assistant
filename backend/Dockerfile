# syntax=docker/dockerfile:1.7
FROM python:3.14-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.14-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 APP_ENV=production
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY scripts ./scripts
COPY tenants ./tenants
COPY knowledge ./knowledge
RUN mkdir -p /app/var && chown app:app /app/var
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status==200 else 1)"
# Graceful shutdown: ECS sends SIGTERM, uvicorn drains in-flight SSE streams for up to 25s.
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "uvloop", "--http", "httptools", "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--timeout-keep-alive", "75", "--timeout-graceful-shutdown", "25", "--no-server-header", "--no-access-log"]
