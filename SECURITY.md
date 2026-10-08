# Security

## Reporting a vulnerability

Email **security@your-company.example** (replace before publishing). Do not open a public issue. We acknowledge within two business days.

## Security model

| Area | Control |
|---|---|
| Edge | CloudFront + AWS WAF: IP-reputation, common and known-bad-input managed rules, per-IP rate limits (global and `/v1/chat*`), optional country allow-list, TLS 1.2+ |
| Origin | ALB security group allows only the CloudFront origin-facing prefix list; the listener forwards only requests carrying a secret `X-Origin-Verify` header; optional TLS between CloudFront and the ALB |
| Network | Tasks and Redis sit in private subnets; egress is HTTPS-only; S3 and DynamoDB use gateway endpoints; VPC flow logs record rejected traffic |
| Identity | Task role limited to `dynamodb:PutItem` on one table and `sns:Publish` on one topic; execution role reads only the app's secrets; GitHub deploys through OIDC with a repository- and environment-scoped trust policy (no static AWS keys) |
| Secrets | Anthropic and Pinecone keys live in Secrets Manager and are injected at task start; they are never in Terraform state, images or Git. Generated secrets (admin key, metrics token) are in state, so the state bucket is private, versioned and encrypted |
| API | Strict request schemas (unknown fields rejected), body-size cap, session-id format validation, constant-time key comparison, per-IP / per-session / per-day rate limits (Redis-backed, fail-open with alerting), admin endpoints behind a separate key and their own limiter, `/metrics` token-protected and never routed through CloudFront |
| LLM | Retrieved passages and user text are delimited as untrusted data; tools are narrow and validated; prices come from a deterministic engine; callbacks need explicit consent and a valid phone number and are rate limited per client; injection attempts are flagged in logs and metrics; no raw prompts are logged |
| Privacy | Logs mask emails and phone numbers; user messages are not logged; client IPs are hashed before use as cache keys; leads expire automatically (`LEADS_RETENTION_DAYS`); sessions expire (`SESSION_TTL_SECONDS`); `DELETE /v1/sessions/{id}` clears a conversation |
| Supply chain | Pinned dependencies, Dependabot, pip-audit / npm audit, Trivy image and IaC scans, gitleaks, CodeQL, immutable ECR tags with scan-on-push, non-root container |
| Browser | Frontend renders model output as React elements only (no HTML injection), safe-protocol links, `Content-Security-Policy: default-src 'none'` on API responses, HSTS |

## Known limits and recommendations

- Heuristic prompt-injection detection is a signal, not a boundary. The boundary is the narrow tool surface and deterministic pricing.
- A browser-shipped API key (`VITE_API_KEY`) is not a secret. Public deployments should rely on WAF and rate limits; use `REQUIRE_API_KEY` for server-to-server or partner embeds.
- Encryption uses AWS-managed keys. If your compliance regime requires customer-managed KMS keys, add them for DynamoDB, Secrets Manager, SNS and CloudWatch Logs.
- Review data-residency requirements per country before routing traffic to a shared Pinecone index or the Anthropic API.
