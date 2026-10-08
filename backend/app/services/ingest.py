"""Knowledge ingestion: parse documents into passages and sync them to Pinecone idempotently.

IDs are ``<source>:<sha1(content)[:16]>``, so re-running is a no-op for unchanged content,
edited entries are re-embedded, and entries removed from the source are deleted (stale cleanup).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.core.logging import get_logger
from app.services.vectorstore import VectorStore

log = get_logger("ingest")

_QA = re.compile(r"Question:\s*(.+?)\s*Answer:\s*(.+?)(?=\n\s*Question:|\Z)", re.S)
_INVISIBLE = re.compile(r"[​‌‍⁠﻿]")
SUPPORTED = {".pdf", ".md", ".txt"}
MAX_CHUNK = 900


@dataclass(slots=True)
class Passage:
    id: str
    text: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class IngestReport:
    tenant: str
    parsed: int = 0
    upserted: int = 0
    unchanged: int = 0
    deleted: int = 0
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _clean(text: str) -> str:
    text = _INVISIBLE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def _pid(source: str, content: str) -> str:
    return f"{source}:{hashlib.sha256(content.encode()).hexdigest()[:16]}"


def read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _chunk(text: str, size: int = MAX_CHUNK, overlap: int = 120) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        p = _clean(p)
        if len(buf) + len(p) + 1 <= size:
            buf = f"{buf} {p}".strip()
            continue
        if buf:
            chunks.append(buf)
        while len(p) > size:
            chunks.append(p[:size])
            p = p[size - overlap :]
        buf = p
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) > 40]


def parse_document(path: Path, tenant: str) -> list[Passage]:
    source = path.stem
    raw = read_pdf(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")
    passages: list[Passage] = []
    seen: set[str] = set()
    pairs = _QA.findall(raw)
    if pairs:
        for q, a in pairs:
            q, a = _clean(q), _clean(a)
            if not q or not a:
                continue
            text = f"Q: {q}\nA: {a}"
            pid = _pid(source, text)
            if pid in seen:
                continue
            seen.add(pid)
            passages.append(Passage(pid, text, {"tenant": tenant, "source": source, "kind": "faq", "question": q[:300]}))
    else:
        for chunk in _chunk(raw):
            pid = _pid(source, chunk)
            if pid in seen:
                continue
            seen.add(pid)
            passages.append(Passage(pid, chunk, {"tenant": tenant, "source": source, "kind": "document"}))
    return passages


def discover(knowledge_dir: Path, tenant: str) -> list[Path]:
    root = knowledge_dir / tenant
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)


async def sync_tenant(store: VectorStore, knowledge_dir: Path, tenant: str) -> IngestReport:
    """Make the tenant namespace match the files on disk."""
    await store.ensure_index()
    report = IngestReport(tenant=tenant)
    for path in discover(knowledge_dir, tenant):
        passages = await asyncio.to_thread(parse_document, path, tenant)
        if not passages:
            log.warning("ingest_no_passages", file=path.name)
            continue
        report.sources.append(path.name)
        report.parsed += len(passages)
        existing = set(await store.list_ids(tenant, f"{path.stem}:"))
        wanted = {p.id for p in passages}
        new = [p for p in passages if p.id not in existing]
        stale = sorted(existing - wanted)
        if new:
            report.upserted += await store.upsert(tenant, [{"id": p.id, "text": p.text, "metadata": p.metadata} for p in new])
        if stale:
            await store.delete(tenant, stale)
        report.unchanged += len(passages) - len(new)
        report.deleted += len(stale)
        log.info("ingest_source_done", file=path.name, parsed=len(passages), upserted=len(new), deleted=len(stale))
    return report
