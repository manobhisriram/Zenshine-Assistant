"""Retrieval: vector search, optional rerank, score thresholding."""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.config import Settings
from app.core import metrics
from app.core.logging import get_logger
from app.services.vectorstore import Match, VectorStore

log = get_logger("rag")


@dataclass(slots=True)
class Retrieval:
    matches: list[Match]
    degraded: bool = False

    @property
    def top_score(self) -> float:
        return self.matches[0].score if self.matches else 0.0

    def as_context(self) -> str:
        return "\n\n".join(f"[{i}] {m.text}" for i, m in enumerate(self.matches, 1))


class Retriever:
    def __init__(self, store: VectorStore, settings: Settings) -> None:
        self._store = store
        self._s = settings

    async def retrieve(self, tenant: str, query: str) -> Retrieval:
        """Never raises: if the vector store is down the bot still answers (without context) and flags it."""
        start = time.perf_counter()
        try:
            matches = await self._store.search(tenant, query, self._s.retrieval_top_k)
            matches = [m for m in matches if m.score >= self._s.retrieval_min_score]
            if matches and self._s.rerank_enabled:
                try:
                    ranked = await self._store.rerank(query, matches, self._s.retrieval_final_k)
                    kept = [m for m in ranked if m.score >= self._s.rerank_min_score]
                    matches = kept or ranked[:1]
                except Exception as exc:  # reranker is an enhancement, not a dependency
                    log.warning("rerank_failed", error_type=type(exc).__name__)
                    matches = matches[: self._s.retrieval_final_k]
            else:
                matches = matches[: self._s.retrieval_final_k]
        except Exception as exc:
            metrics.RETRIEVAL_ERRORS.inc()
            log.error("retrieval_failed", error_type=type(exc).__name__)
            return Retrieval([], degraded=True)
        finally:
            metrics.RETRIEVAL_LATENCY.observe(time.perf_counter() - start)
        if matches:
            metrics.RETRIEVAL_TOP_SCORE.observe(min(1.0, matches[0].score))
        else:
            metrics.RETRIEVAL_EMPTY.inc()
        return Retrieval(matches)
