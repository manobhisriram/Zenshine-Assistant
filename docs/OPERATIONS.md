# Operations

## Dashboards and alarms
CloudWatch dashboard `<name>` shows requests and 5xx, time-to-first-token p50/p95/p99, CPU and memory, running tasks, chat turns/errors/fallbacks and token usage (including cache-read tokens, which show prompt-cache effectiveness). Alarms notify the `<name>-alarms` SNS topic.

| Alarm | Meaning | First action |
|---|---|---|
| `alb-5xx` | Tasks returning 5xx | Check `chat_stream_failed` / `llm_error` logs; recent deploy? roll back |
| `unhealthy-hosts` | Targets failing `/healthz` | ECS events; task crash loops (often a missing or invalid secret) |
| `running-tasks-low` | Below `min_tasks` | Capacity, image pull, secrets |
| `cpu-high` | Sustained CPU > 85% | Raise `max_tasks`, check for abuse in WAF metrics |
| `time-to-first-token-p95` | Slow starts | Look at `retrieval_duration_seconds`, Anthropic status, fallbacks |
| `llm-fallbacks` | Primary model failing | Anthropic status or rate limits; verify account limits |
| `chat-errors` | Turns failing even after fallback | Anthropic outage, invalid key, Pinecone and Anthropic quotas |
| `redis-cpu` | Redis saturated | Scale node type |

Targets to start from (tune with real traffic): availability 99.9%, TTFT p95 < 3 s, error rate < 1%.

## Logs
JSON, one event per line, with `request_id` for correlation (also returned as `X-Request-ID`). Useful CloudWatch Logs Insights queries:

```
fields @timestamp, event, model, in_tokens, out_tokens, cache_read, duration_ms | filter event = "chat_turn" | sort @timestamp desc
fields @timestamp, event, error_type | filter level = "error" | stats count() by event, error_type
filter event = "prompt_injection_suspected" | stats count() by bin(1h)
```

## Common tasks
- **Update knowledge.** Replace files in `backend/knowledge/<tenant>/` and deploy (auto-ingest syncs on start), or call `POST /v1/admin/ingest` with `X-Admin-Key`. Unchanged entries are skipped; edited entries are re-embedded; removed entries are deleted.
- **Change prices or services.** Edit `backend/tenants/<tenant>.yaml` and deploy. The prompt and quote engine both read from it.
- **Rotate keys.** `put-secret-value` then `update-service --force-new-deployment`. Admin key: taint `random_password.admin_key` and apply.
- **Roll back.** The deploy circuit breaker rolls back failed deployments automatically. For a bad-but-healthy release, rerun the Deploy workflow on the previous commit (its image already exists in ECR).
- **Read leads.** DynamoDB table `<name>-leads`, or the SNS email alerts.
- **Delete a user's conversation.** `DELETE /v1/sessions/{id}`; leads can be removed from DynamoDB by `lead_id`.

## Capacity planning
Each task is I/O bound (waiting on Pinecone and Anthropic), so one task handles many concurrent streams. Load test with `make load BASE_URL=...` (k6, `tests/load/chat.js`) against a staging stack, find CPU per concurrent stream, and set `target_cpu_percent`, `max_tasks` and Anthropic/Pinecone rate-limit tiers accordingly. Expect your Anthropic account's rate limits, not compute, to be the first ceiling.

## Content data quality
The source FAQ lists the *Premium Full Home* package at ₹7,500 although its listed components sum to ₹6,500 (₹6,200 with the free door and window cleaning). The tenant file keeps the published package prices (₹7,500 list, ₹6,000 after the 20% combo discount, ₹5,900 with the first-time discount). Confirm the intended numbers with the business and update `tenants/zenshine.yaml` and `faq.pdf`.
