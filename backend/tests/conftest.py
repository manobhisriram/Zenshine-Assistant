from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anthropic
import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")

from app.api.deps import Container  # noqa: E402
from app.config import Settings  # noqa: E402
from app.core.ratelimit import MemoryCounter, RateLimiter  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.agent import ChatAgent  # noqa: E402
from app.services.leads import FileLeadStore, LeadService  # noqa: E402
from app.services.memory import MemorySessionStore  # noqa: E402
from app.services.rag import Retriever  # noqa: E402
from app.services.tenants import load_registry  # noqa: E402
from app.services.vectorstore import Match  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class FakeStore:
    """In-memory stand-in for Pinecone with naive keyword scoring."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {}
        self.fail = False

    async def ensure_index(self) -> None: ...

    async def upsert(self, namespace, records):
        ns = self.data.setdefault(namespace, {})
        for r in records:
            ns[r["id"]] = r
        return len(records)

    async def search(self, namespace, query, top_k):
        if self.fail:
            raise RuntimeError("pinecone down")
        words = {w for w in query.lower().split() if len(w) > 2}
        scored = []
        for r in self.data.get(namespace, {}).values():
            hit = len(words & set(r["text"].lower().split()))
            if hit:
                scored.append(Match(r["id"], min(1.0, 0.2 + hit / 5), r["text"], dict(r["metadata"])))
        return sorted(scored, key=lambda m: -m.score)[:top_k]

    async def rerank(self, query, matches, top_n):
        return matches[:top_n]

    async def count(self, namespace):
        return len(self.data.get(namespace, {}))

    async def list_ids(self, namespace, prefix):
        return [i for i in self.data.get(namespace, {}) if i.startswith(prefix)]

    async def delete(self, namespace, ids):
        for i in ids:
            self.data.get(namespace, {}).pop(i, None)

    async def ping(self):
        return not self.fail


# ── Anthropic wire-format mock ────────────────────────────────────────────
def sse_body(blocks: list[dict[str, Any]], stop_reason: str = "end_turn") -> bytes:
    def ev(name: str, data: dict[str, Any]) -> str:
        return f"event: {name}\ndata: {json.dumps(data)}\n\n"

    out = [
        ev(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 80,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        )
    ]
    for i, b in enumerate(blocks):
        if b["type"] == "text":
            out.append(
                ev(
                    "content_block_start",
                    {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                )
            )
            for piece in b["pieces"]:
                out.append(
                    ev(
                        "content_block_delta",
                        {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": piece}},
                    )
                )
        else:
            out.append(
                ev(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": i,
                        "content_block": {"type": "tool_use", "id": b["id"], "name": b["name"], "input": {}},
                    },
                )
            )
            out.append(
                ev(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])},
                    },
                )
            )
        out.append(ev("content_block_stop", {"type": "content_block_stop", "index": i}))
    out.append(
        ev(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 42},
            },
        )
    )
    out.append(ev("message_stop", {"type": "message_stop"}))
    return "".join(out).encode()


class ScriptedAnthropic:
    """Plays queued responses (bytes body, or an int status for an error) and records the requests."""

    def __init__(self) -> None:
        self.queue: list[Any] = []
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        item = self.queue.pop(0) if self.queue else sse_body([{"type": "text", "pieces": ["ok"]}])
        if isinstance(item, int):
            return httpx.Response(
                item,
                json={"type": "error", "error": {"type": "overloaded_error" if item == 529 else "api_error", "message": "boom"}},
            )
        return httpx.Response(200, content=item, headers={"content-type": "text/event-stream"})


def make_settings(tmp_path: Path, **over: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "test",
        "anthropic_api_key": "sk-ant-test",
        "pinecone_api_key": "pc-test",
        "tenants_dir": str(ROOT / "tenants"),
        "knowledge_dir": str(ROOT / "knowledge"),
        "leads_file_path": str(tmp_path / "leads.jsonl"),
        "admin_api_key": "a" * 32,
        "auto_ingest": False,
        "metrics_token": "m-token",
        "anthropic_max_retries": 0,
        "trusted_proxy_hops": 0,
    }
    base.update(over)
    return Settings(_env_file=None, **base)


@pytest.fixture
def anthropic_mock() -> ScriptedAnthropic:
    return ScriptedAnthropic()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def build(tmp_path, anthropic_mock, store) -> Callable[..., Container]:
    def _build(**over: Any) -> Container:
        s = make_settings(tmp_path, **over)
        client = anthropic.AsyncAnthropic(
            api_key="sk-ant-test",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(anthropic_mock.handler)),
        )
        return Container(
            settings=s,
            registry=load_registry(s.tenants_dir),
            limiter=RateLimiter(MemoryCounter()),
            sessions=MemorySessionStore(s.history_turns, s.session_ttl_seconds),
            leads=LeadService(FileLeadStore(s.leads_file_path), s),
            store=store,
            retriever=Retriever(store, s),
            agent=ChatAgent(client, s),
        )

    return _build


@pytest.fixture
def make_client(build) -> Callable[..., TestClient]:
    def _make(**over: Any) -> TestClient:
        c = build(**over)
        return TestClient(create_app(c.settings, c))

    return _make


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c
