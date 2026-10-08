"""Pinecone vector store: serverless index, hosted embeddings and hosted reranking.

The Pinecone SDK is synchronous, so every call runs in a worker thread behind a bounded
CapacityLimiter. That keeps the event loop free and caps concurrent upstream calls.
Each tenant gets its own namespace, so tenants are isolated at the storage layer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol, TypeVar

import anyio
from anyio import CapacityLimiter, to_thread

from app.config import Settings
from app.core.logging import get_logger

log = get_logger("vectorstore")
T = TypeVar("T")

EMBED_BATCH = 96  # hosted-embedding request limit for multilingual-e5-large
UPSERT_BATCH = 100


@dataclass(slots=True)
class Match:
    id: str
    score: float
    text: str
    metadata: dict[str, Any]


class VectorStore(Protocol):
    async def ensure_index(self) -> None: ...
    async def upsert(self, namespace: str, records: list[dict[str, Any]]) -> int: ...
    async def search(self, namespace: str, query: str, top_k: int) -> list[Match]: ...
    async def rerank(self, query: str, matches: list[Match], top_n: int) -> list[Match]: ...
    async def count(self, namespace: str) -> int: ...
    async def list_ids(self, namespace: str, prefix: str) -> list[str]: ...
    async def delete(self, namespace: str, ids: list[str]) -> None: ...
    async def ping(self) -> bool: ...


class PineconeStore:
    def __init__(self, settings: Settings) -> None:
        if not settings.pinecone_api_key:
            raise RuntimeError("PINECONE_API_KEY is not set")
        from pinecone import Pinecone

        self._s = settings
        self._pc = Pinecone(api_key=settings.pinecone_api_key, source_tag="zenshine-assistant")
        self._index: Any = None
        self._limiter = CapacityLimiter(settings.pinecone_concurrency)
        self._lock = asyncio.Lock()

    async def _run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return await to_thread.run_sync(partial(fn, *args, **kwargs), limiter=self._limiter)

    async def ensure_index(self) -> None:
        async with self._lock:
            if self._index is not None:
                return
            from pinecone import ServerlessSpec

            name = self._s.pinecone_index
            if not await self._run(self._pc.has_index, name):
                log.info("pinecone_creating_index", index=name, region=self._s.pinecone_region)
                await self._run(
                    self._pc.create_index,
                    name=name,
                    dimension=self._s.pinecone_embed_dimension,
                    metric="cosine",
                    spec=ServerlessSpec(cloud=self._s.pinecone_cloud, region=self._s.pinecone_region),
                    deletion_protection="enabled" if self._s.pinecone_deletion_protection else "disabled",
                    timeout=300,
                )
            desc = await self._run(self._pc.describe_index, name)
            if int(desc.dimension) != self._s.pinecone_embed_dimension:
                raise RuntimeError(f"Index '{name}' has dimension {desc.dimension}, expected {self._s.pinecone_embed_dimension}")
            self._index = self._pc.Index(host=desc.host)

    async def _idx(self) -> Any:
        if self._index is None:
            await self.ensure_index()
        return self._index

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i : i + EMBED_BATCH]
            res = await self._run(
                self._pc.inference.embed,
                model=self._s.pinecone_embed_model,
                inputs=batch,
                parameters={"input_type": input_type, "truncate": "END"},
            )
            vectors.extend([list(map(float, e["values"])) for e in res])
        return vectors

    async def upsert(self, namespace: str, records: list[dict[str, Any]]) -> int:
        """records: {id, text, metadata}. Embeds as passages, upserts in batches."""
        if not records:
            return 0
        idx = await self._idx()
        vectors = await self._embed([r["text"] for r in records], "passage")
        payload = [
            {"id": r["id"], "values": v, "metadata": {**r.get("metadata", {}), "text": r["text"]}}
            for r, v in zip(records, vectors, strict=True)
        ]
        for i in range(0, len(payload), UPSERT_BATCH):
            await self._run(idx.upsert, vectors=payload[i : i + UPSERT_BATCH], namespace=namespace)
        return len(payload)

    async def search(self, namespace: str, query: str, top_k: int) -> list[Match]:
        idx = await self._idx()
        (vec,) = await self._embed([query], "query")
        res = await self._run(idx.query, vector=vec, top_k=top_k, namespace=namespace, include_metadata=True)
        out: list[Match] = []
        for m in res["matches"]:
            md = dict(m.get("metadata") or {})
            out.append(Match(id=m["id"], score=float(m["score"]), text=str(md.pop("text", "")), metadata=md))
        return out

    async def rerank(self, query: str, matches: list[Match], top_n: int) -> list[Match]:
        if len(matches) <= 1:
            return matches[:top_n]
        res = await self._run(
            self._pc.inference.rerank,
            model=self._s.pinecone_rerank_model,
            query=query,
            documents=[{"id": m.id, "text": m.text} for m in matches],
            rank_fields=["text"],
            top_n=min(top_n, len(matches)),
            return_documents=False,
        )
        ranked = []
        for row in res.data:
            base = matches[row["index"]]
            ranked.append(Match(id=base.id, score=float(row["score"]), text=base.text, metadata=base.metadata))
        return ranked

    async def count(self, namespace: str) -> int:
        idx = await self._idx()
        stats = await self._run(idx.describe_index_stats)
        ns = (stats.get("namespaces") or {}).get(namespace)
        return int(ns["vector_count"]) if ns else 0

    async def list_ids(self, namespace: str, prefix: str) -> list[str]:
        idx = await self._idx()

        def _collect() -> list[str]:
            ids: list[str] = []
            for page in idx.list(prefix=prefix, namespace=namespace):
                ids.extend(page)
            return ids

        return await self._run(_collect)

    async def delete(self, namespace: str, ids: list[str]) -> None:
        idx = await self._idx()
        for i in range(0, len(ids), 500):
            await self._run(idx.delete, ids=ids[i : i + 500], namespace=namespace)

    async def ping(self) -> bool:
        try:
            with anyio.fail_after(3):
                await self._run(self._pc.has_index, self._s.pinecone_index)
            return True
        except Exception as exc:
            log.warning("pinecone_ping_failed", error_type=type(exc).__name__)
            return False
