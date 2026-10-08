# Contributing

1. Branch from `main`; keep PRs focused.
2. `make install`, then `make lint test` before pushing.
3. Backend: Python 3.11, ruff + mypy clean, tests for new behaviour (fakes live in `backend/tests/conftest.py`: scripted Anthropic wire stream, in-memory vector store).
4. Frontend: TypeScript strict, vitest for logic and components.
5. Infrastructure: `terraform fmt`, attach the plan to the PR.
6. Never commit secrets or real customer data. Configuration changes that add environment variables must update `.env.example` and `README.md`.
