"""Callback-request capture. Stored in DynamoDB (TTL-expired) or a JSONL file, with an SNS alert to the team."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings
from app.core import metrics
from app.core.logging import get_logger

log = get_logger("leads")

_PHONE = re.compile(r"^\+?[0-9][0-9 \-()]{6,18}[0-9]$")


def valid_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return bool(_PHONE.match(value.strip())) and 8 <= len(digits) <= 15


class LeadStore(Protocol):
    async def save(self, lead: dict[str, Any]) -> str: ...
    async def ping(self) -> bool: ...


class FileLeadStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def save(self, lead: dict[str, Any]) -> str:
        lead_id = uuid.uuid4().hex
        record = {"lead_id": lead_id, "created_at": int(time.time()), **lead}
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._append, record)
        return lead_id

    def _append(self, record: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def ping(self) -> bool:
        return True


class DynamoLeadStore:
    def __init__(self, settings: Settings) -> None:
        import boto3

        self._table = boto3.resource("dynamodb", region_name=settings.aws_region).Table(settings.leads_dynamodb_table)
        self._ttl = settings.leads_retention_days * 86400

    async def save(self, lead: dict[str, Any]) -> str:
        lead_id = uuid.uuid4().hex
        now = int(time.time())
        item = {
            "lead_id": lead_id,
            "tenant": lead["tenant"],
            "created_at": now,
            "expires_at": now + self._ttl,
            **{k: v for k, v in lead.items() if k != "tenant" and v not in (None, "")},
        }
        await asyncio.to_thread(self._table.put_item, Item=item)
        return lead_id

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(lambda: self._table.table_status)
            return True
        except Exception:
            return False


class LeadService:
    """Persists a lead and notifies the team. Notification failure never loses the lead."""

    def __init__(self, store: LeadStore, settings: Settings) -> None:
        self._store = store
        self._topic = settings.leads_sns_topic_arn
        self._region = settings.aws_region
        self._sns: Any = None

    async def capture(self, lead: dict[str, Any]) -> str:
        lead_id = await self._store.save(lead)
        metrics.LEADS.labels(outcome="saved").inc()
        log.info("lead_saved", lead_id=lead_id, tenant=lead.get("tenant"))
        if self._topic:
            try:
                await asyncio.to_thread(self._publish, lead_id, lead)
            except Exception as exc:
                metrics.LEADS.labels(outcome="notify_failed").inc()
                log.error("lead_notify_failed", lead_id=lead_id, error_type=type(exc).__name__)
        return lead_id

    def _publish(self, lead_id: str, lead: dict[str, Any]) -> None:
        import boto3

        if self._sns is None:
            self._sns = boto3.client("sns", region_name=self._region)
        body = (
            f"New callback request ({lead.get('tenant')})\n"
            f"Name: {lead.get('name')}\nPhone: {lead.get('phone')}\n"
            f"Service interest: {lead.get('interest') or '-'}\nPreferred time: {lead.get('preferred_time') or '-'}\n"
            f"Lead ID: {lead_id}"
        )
        self._sns.publish(TopicArn=self._topic, Subject="New callback request", Message=body)

    async def ping(self) -> bool:
        return await self._store.ping()


def build_lead_service(settings: Settings) -> LeadService:
    store: LeadStore = (
        DynamoLeadStore(settings) if settings.leads_backend == "dynamodb" else FileLeadStore(settings.leads_file_path)
    )
    return LeadService(store, settings)
