from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    tenant: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9_-]+$")

    @field_validator("session_id")
    @classmethod
    def _valid_session(cls, v: str | None) -> str | None:
        if v is not None and not SESSION_RE.match(v):
            raise ValueError("session_id must be 8-64 chars of [A-Za-z0-9_-]")
        return v


class ChatResponse(BaseModel):
    session_id: str
    message_id: str
    answer: str
    sources: list[dict]
    model: str
    tools_used: list[str]


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    message_id: str = Field(min_length=8, max_length=64)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("session_id")
    @classmethod
    def _valid_session(cls, v: str) -> str:
        if not SESSION_RE.match(v):
            raise ValueError("invalid session_id")
        return v


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant: str | None = Field(default=None, pattern=r"^[a-z0-9_-]+$")
