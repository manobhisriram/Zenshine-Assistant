"""Prometheus metrics plus CloudWatch Embedded Metric Format (EMF) emission.

Prometheus series are exposed on /metrics (token-protected, blocked at the load balancer).
EMF lines are written to stdout; CloudWatch Logs turns them into CloudWatch metrics with no agent,
which is what the alarms in infrastructure/ are built on.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

_LAT = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34)

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_LATENCY = Histogram("http_request_duration_seconds", "HTTP latency", ["route"], buckets=_LAT, registry=REGISTRY)
CHAT_TTFT = Histogram(
    "chat_time_to_first_token_seconds", "Time to first streamed token", ["model"], buckets=_LAT, registry=REGISTRY
)
CHAT_TOTAL = Histogram("chat_total_seconds", "End-to-end chat turn latency", ["model"], buckets=_LAT, registry=REGISTRY)
LLM_TOKENS = Counter("llm_tokens_total", "LLM tokens", ["model", "kind"], registry=REGISTRY)
LLM_ERRORS = Counter("llm_errors_total", "LLM errors", ["model", "type"], registry=REGISTRY)
LLM_FALLBACKS = Counter("llm_fallbacks_total", "Fallback model activations", registry=REGISTRY)
TOOL_CALLS = Counter("tool_calls_total", "Tool invocations", ["tool", "outcome"], registry=REGISTRY)
RETRIEVAL_LATENCY = Histogram("retrieval_duration_seconds", "Embed + vector search + rerank", buckets=_LAT, registry=REGISTRY)
RETRIEVAL_TOP_SCORE = Histogram(
    "retrieval_top_score",
    "Best match score per query",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    registry=REGISTRY,
)
RETRIEVAL_EMPTY = Counter("retrieval_empty_total", "Queries with no passage above threshold", registry=REGISTRY)
RETRIEVAL_ERRORS = Counter("retrieval_errors_total", "Retrieval failures (answered without context)", registry=REGISTRY)
RATE_LIMITED = Counter("rate_limited_total", "Requests rejected by rate limiting", ["scope"], registry=REGISTRY)
INJECTION_FLAGS = Counter("prompt_injection_flags_total", "Messages matching injection heuristics", registry=REGISTRY)
FEEDBACK = Counter("feedback_total", "User feedback", ["rating"], registry=REGISTRY)
LEADS = Counter("leads_total", "Callback requests captured", ["outcome"], registry=REGISTRY)
ACTIVE_STREAMS = Gauge("active_streams", "In-flight streaming chats", registry=REGISTRY)


def emit_emf(
    namespace: str, metrics: Mapping[str, tuple[float, str]], dimensions: Mapping[str, str], enabled: bool = True
) -> None:
    """Write one CloudWatch EMF record. ``metrics`` maps name -> (value, unit)."""
    if not enabled:
        return
    record = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": [list(dimensions.keys())] if dimensions else [[]],
                    "Metrics": [{"Name": n, "Unit": u} for n, (_, u) in metrics.items()],
                }
            ],
        },
        **dimensions,
        **{n: v for n, (v, _) in metrics.items()},
    }
    sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")
    sys.stdout.flush()
