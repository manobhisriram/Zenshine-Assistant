"""Typed application settings, loaded from environment variables (and a local .env in development)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ── Runtime ───────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production", "test"] = "development"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    default_tenant: str = "zenshine"
    tenants_dir: str = "tenants"
    knowledge_dir: str = "knowledge"
    # Comma-separated allowed browser origins. "*" is rejected in production.
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    # Number of trusted reverse proxies in front of the app (CloudFront + ALB = 2, ALB only = 1).
    trusted_proxy_hops: int = 1
    max_request_bytes: int = 64 * 1024

    # ── Anthropic ─────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_fallback_model: str = "claude-haiku-4-5-20251001"
    anthropic_max_tokens: int = 1024
    anthropic_timeout_seconds: float = 60.0
    anthropic_max_retries: int = 2

    # ── Pinecone ──────────────────────────────────────────────────────────
    pinecone_api_key: str = ""
    pinecone_index: str = "zenshine-assistant"
    pinecone_cloud: Literal["aws", "gcp", "azure"] = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_embed_model: str = "multilingual-e5-large"
    pinecone_embed_dimension: int = 1024
    pinecone_rerank_model: str = "bge-reranker-v2-m3"
    pinecone_concurrency: int = 16
    pinecone_deletion_protection: bool = False

    # ── Retrieval ─────────────────────────────────────────────────────────
    retrieval_top_k: int = 8
    retrieval_final_k: int = 4
    retrieval_min_score: float = 0.30
    rerank_enabled: bool = True
    rerank_min_score: float = 0.05
    auto_ingest: bool = True

    # ── Conversation ──────────────────────────────────────────────────────
    redis_url: str = ""
    history_turns: int = 8
    session_ttl_seconds: int = 60 * 60 * 6
    max_message_chars: int = 1200
    max_tool_rounds: int = 4

    # ── Abuse protection ──────────────────────────────────────────────────
    rate_limit_ip_per_minute: int = 30
    rate_limit_session_per_minute: int = 15
    rate_limit_ip_per_day: int = 600
    rate_limit_ingest_per_hour: int = 6

    # ── Access control ────────────────────────────────────────────────────
    admin_api_key: str = ""
    # Comma-separated keys. When require_api_key is true, /v1/chat* needs a valid X-API-Key.
    api_keys: str = ""
    require_api_key: bool = False
    metrics_token: str = ""

    # ── Leads (callback requests) ─────────────────────────────────────────
    leads_backend: Literal["file", "dynamodb"] = "file"
    leads_file_path: str = "var/leads.jsonl"
    leads_dynamodb_table: str = ""
    leads_sns_topic_arn: str = ""
    leads_retention_days: int = 90
    aws_region: str = "us-east-1"

    # ── Observability ─────────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "zenshine-assistant-api"
    emf_namespace: str = "ZenShineAssistant"
    emf_enabled: bool = False

    # ── Derived helpers ───────────────────────────────────────────────────
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @field_validator("anthropic_api_key", "pinecone_api_key")
    @classmethod
    def _blank_placeholders(cls, v: str) -> str:
        v = v.strip()
        return "" if v.upper() in {"REPLACE_ME", "CHANGEME", "YOUR_KEY_HERE"} else v

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.is_production:
            if "*" in self.cors_origin_list:
                raise ValueError("CORS_ORIGINS must list explicit origins in production")
            if not self.admin_api_key or len(self.admin_api_key) < 24:
                raise ValueError("ADMIN_API_KEY (>= 24 chars) is required in production")
        if self.require_api_key and not self.api_key_list:
            raise ValueError("REQUIRE_API_KEY is true but API_KEYS is empty")
        if self.leads_backend == "dynamodb" and not self.leads_dynamodb_table:
            raise ValueError("LEADS_DYNAMODB_TABLE is required when LEADS_BACKEND=dynamodb")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
