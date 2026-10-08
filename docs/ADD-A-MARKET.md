# Add a market or brand

1. Copy `backend/tenants/zenshine.yaml` to `backend/tenants/<id>.yaml`. The `id` must match the file name. Set brand, `locale` (default and supported languages, timezone), `currency` (code, symbol, decimals), `contact`, `services` with prices, `discounts`, `packages` and `ui` copy. Services, packages and discounts are validated on start-up (unknown references fail fast).
2. Put the knowledge in `backend/knowledge/<id>/`. Supported: `.pdf`, `.md`, `.txt`. Documents written as `Question: ... Answer: ...` pairs are indexed one pair per passage; other text is chunked by paragraph.
3. Ingest: `make ingest` (CLI: `python -m scripts.ingest --tenant <id>`) or `POST /v1/admin/ingest {"tenant":"<id>"}`.
4. Route the tenant: set `VITE_TENANT=<id>` for a dedicated web build, or send `"tenant":"<id>"` in API calls. Each tenant has its own Pinecone namespace.
5. Tenant-specific pricing rules beyond the supported ones (combo tiers, flat first-time and referral discounts, monthly-contract percentage, free add-ons) belong in `app/services/pricing.py` with tests.

Languages: the model replies in the customer's language, and `multilingual-e5-large` embeds queries across 100+ languages against the (usually English) knowledge base. For best quality in a new language, add native-language FAQ entries.
