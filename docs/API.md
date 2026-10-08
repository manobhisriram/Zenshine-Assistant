# API reference

Base path `/v1`. JSON errors look like `{"error": {"code", "message", "request_id"}}`. Interactive docs are served at `/docs` outside production.

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/v1/chat/stream` | `X-API-Key` if `REQUIRE_API_KEY` | Streaming chat (Server-Sent Events) |
| POST | `/v1/chat` | same | One-shot chat (JSON) |
| GET | `/v1/config` | none | Public tenant config for the UI |
| POST | `/v1/feedback` | none (rate limited) | Thumbs up/down on a message |
| DELETE | `/v1/sessions/{id}` | none | Clear a conversation |
| POST | `/v1/admin/ingest` | `X-Admin-Key` | Re-sync the knowledge base |
| GET | `/v1/admin/status` | `X-Admin-Key` | Ingest state and vector count |
| GET | `/healthz` | none | Liveness |
| GET | `/readyz` | none | Readiness (Redis, Pinecone, leads store) |
| GET | `/metrics` | `Authorization: Bearer <METRICS_TOKEN>` | Prometheus |

## Chat request
```json
{ "message": "House cleaning and kitchen, first time customer", "session_id": "optional 8-64 chars [A-Za-z0-9_-]", "tenant": "zenshine" }
```
Omit `session_id` on the first turn; the server returns one in the `meta` event (or response body).

## Stream events
```
event: meta     data: {"session_id","message_id","request_id"}
event: tool     data: {"name":"calculate_quote","status":"running|done|error"}
event: delta    data: {"text":"..."}
event: sources  data: {"sources":[{"id","score","question"}]}
event: done     data: {"message_id","model","tools_used":[],"latency_ms"}
event: error    data: {"code","message"}
```

## Limits
Message 1,200 characters by default (`MAX_MESSAGE_CHARS`), body 64 KB, per IP 30/min and 600/day, per session 15/min. 429 responses carry `Retry-After`.

```bash
curl -N -X POST http://localhost:8000/v1/chat/stream -H 'Content-Type: application/json' \
  -d '{"message":"What are your working hours?"}'
```
