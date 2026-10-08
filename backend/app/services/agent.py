"""The chat agent: retrieval-grounded Claude with tool use, streaming, model fallback and a circuit breaker.

``ChatAgent.stream`` is an async generator of ``(event, data)`` pairs that the API layer turns into
Server-Sent Events: ``meta`` -> (``tool``)* -> ``delta``* -> ``sources`` -> ``done`` (or ``error``).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.config import Settings
from app.core import metrics
from app.core.circuit import CircuitBreaker
from app.core.logging import get_logger
from app.prompts.system import build_context_block, build_static_prompt
from app.services.guardrails import neutralize_context
from app.services.rag import Retrieval
from app.services.tenants import Tenant
from app.services.tools import ToolContext, execute_tool, tool_specs

log = get_logger("agent")

Event = tuple[str, dict[str, Any]]
FALLBACK_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
    anthropic.RateLimitError,
    anthropic.OverloadedError,
    anthropic.ServiceUnavailableError,
)
SAFE_ERROR_TEXT = "I'm having trouble answering right now. Please try again in a moment, or call us directly."


@dataclass(slots=True)
class TurnResult:
    text: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    tools_used: list[str] = field(default_factory=list)
    fallback_used: bool = False
    ttft_ms: float | None = None
    error: bool = False


def build_llm_client(settings: Settings) -> anthropic.AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.anthropic_timeout_seconds,
        max_retries=settings.anthropic_max_retries,
    )


class ChatAgent:
    def __init__(self, client: anthropic.AsyncAnthropic, settings: Settings) -> None:
        self._client = client
        self._s = settings
        self._breaker = CircuitBreaker(failure_threshold=5, reset_seconds=30)
        self._system_cache: dict[str, list[dict[str, Any]]] = {}

    def _system(self, tenant: Tenant) -> list[dict[str, Any]]:
        if tenant.id not in self._system_cache:
            self._system_cache[tenant.id] = [
                {"type": "text", "text": build_static_prompt(tenant), "cache_control": {"type": "ephemeral"}}
            ]
        return self._system_cache[tenant.id]

    def _models(self) -> list[str]:
        primary, fallback = self._s.anthropic_model, self._s.anthropic_fallback_model
        if not fallback or fallback == primary:
            return [primary]
        return [fallback] if self._breaker.is_open else [primary, fallback]

    async def stream(
        self,
        *,
        tenant: Tenant,
        history: list[dict[str, str]],
        user_message: str,
        retrieval: Retrieval,
        tool_ctx: ToolContext,
        result: TurnResult,
    ) -> AsyncIterator[Event]:
        context = neutralize_context(retrieval.as_context())
        user_turn = f"{build_context_block(context)}\n\n<customer_message>\n{user_message}\n</customer_message>"
        messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_turn}]
        tools = tool_specs(tenant)
        system = self._system(tenant)

        turn_started = time.perf_counter()
        for round_no in range(self._s.max_tool_rounds + 1):
            allow_tools = round_no < self._s.max_tool_rounds
            final_message: Any = None
            emitted = False
            models = self._models()
            last_exc: Exception | None = None

            for attempt, model in enumerate(models):
                if attempt:
                    metrics.LLM_FALLBACKS.inc()
                    result.fallback_used = True
                    log.warning("llm_fallback", from_model=models[0], to_model=model)
                started = time.perf_counter()
                first_token_at: float | None = None
                try:
                    kwargs: dict[str, Any] = {
                        "model": model,
                        "max_tokens": self._s.anthropic_max_tokens,
                        "system": system,
                        "messages": messages,
                    }
                    if allow_tools:
                        kwargs["tools"] = tools
                    async with self._client.messages.stream(**kwargs) as stream:
                        async for event in stream:
                            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                                if first_token_at is None:
                                    first_token_at = time.perf_counter()
                                    metrics.CHAT_TTFT.labels(model=model).observe(first_token_at - started)
                                    if result.ttft_ms is None:
                                        result.ttft_ms = (first_token_at - turn_started) * 1000
                                emitted = True
                                result.text += event.delta.text
                                yield "delta", {"text": event.delta.text}
                        final_message = await stream.get_final_message()
                    result.model = model
                    if model == self._s.anthropic_model:
                        self._breaker.record_success()
                    self._record_usage(model, final_message, result)
                    metrics.CHAT_TOTAL.labels(model=model).observe(time.perf_counter() - started)
                    break
                except FALLBACK_ERRORS as exc:
                    last_exc = exc
                    metrics.LLM_ERRORS.labels(model=model, type=type(exc).__name__).inc()
                    if model == self._s.anthropic_model:
                        self._breaker.record_failure()
                    log.error("llm_error", model=model, error_type=type(exc).__name__, emitted=emitted)
                    if emitted:  # can't transparently retry once tokens reached the client
                        break
                except anthropic.APIStatusError as exc:
                    metrics.LLM_ERRORS.labels(model=model, type=type(exc).__name__).inc()
                    log.error("llm_status_error", model=model, status=exc.status_code)
                    last_exc = exc
                    break
            if final_message is None:
                raise last_exc or RuntimeError("no model available")

            if final_message.stop_reason != "tool_use" or not allow_tools:
                if final_message.stop_reason == "max_tokens":
                    log.warning("llm_truncated", model=result.model)
                return

            # ── Tool round ────────────────────────────────────────────────
            messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in final_message.content]})
            tool_results: list[dict[str, Any]] = []
            for block in final_message.content:
                if block.type != "tool_use":
                    continue
                yield "tool", {"name": block.name, "status": "running"}
                output, is_error = await execute_tool(block.name, dict(block.input), tool_ctx)
                result.tools_used.append(block.name)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(output, ensure_ascii=False),
                        **({"is_error": True} if is_error else {}),
                    }
                )
                yield "tool", {"name": block.name, "status": "error" if is_error else "done"}
            messages.append({"role": "user", "content": tool_results})
            if emitted:
                result.text += "\n\n"
                yield "delta", {"text": "\n\n"}

    @staticmethod
    def _record_usage(model: str, message: Any, result: TurnResult) -> None:
        usage = message.usage
        inp = int(getattr(usage, "input_tokens", 0) or 0)
        out = int(getattr(usage, "output_tokens", 0) or 0)
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        result.input_tokens += inp + cache_read + cache_write
        result.output_tokens += out
        result.cache_read_tokens += cache_read
        for kind, n in (("input", inp), ("output", out), ("cache_read", cache_read), ("cache_write", cache_write)):
            if n:
                metrics.LLM_TOKENS.labels(model=model, kind=kind).inc(n)
