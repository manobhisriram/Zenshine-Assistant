# Design decisions

**Pinecone hosted inference for embeddings and reranking.** One vendor and one API key replace a bundled local model (`all-MiniLM-L6-v2`, English-focused, with a heavy PyTorch dependency) and keep the containers small and fast to scale. `multilingual-e5-large` is multilingual, which the multi-country requirement needs. Trade-off: a network hop per query (embedding) that a local model would not pay; mitigated by one batched call and the cache-friendly prompt.

**Deterministic quote tool instead of prompt arithmetic.** The prototype asked the model to calculate totals. Totals now come from `calculate_quote`, tested against the FAQ's worked examples. The model explains; it does not compute.

**ID-prefix cleanup for stale vectors.** Pinecone serverless cannot delete by metadata filter, so passage ids are `<source>:<sha256>` and ingestion lists ids by prefix to find removed or edited entries.

**Pure-ASGI middleware.** Starlette's `BaseHTTPMiddleware` interferes with streaming responses; request context, size limits and headers are implemented as raw ASGI so SSE is never buffered.

**Redis with in-memory fallback.** Required for correctness with more than one task; the fallback keeps local development dependency-free and is logged loudly in production.

**Fail-open rate limiting, fail-fast secrets.** A Redis blip must not take the assistant down (alarms catch it); a missing API key must stop the deploy rather than serve a broken bot.

**pypdf instead of PyMuPDF.** PyMuPDF is AGPL-licensed, which is a problem for proprietary client delivery.

**No Streamlit.** Streamlit reruns the script per interaction and ties UI to server memory, which does not scale horizontally or stream well through CDNs. The UI is a static React app; the API is stateless.

**Single Terraform root with tfvars per environment.** Simple to read and review; modules can be extracted if teams need to share pieces.

**Removed from the prototype:** `httpx.Client(verify=False)` (TLS verification was disabled for Groq calls), the Windows SSL workaround, hardcoded prices in code, the owner's personal email in the prompt, and runtime API-key entry in the UI sidebar.
