.PHONY: help install dev test lint fmt ingest up down tf-plan load

help:           ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:        ## Install backend + frontend dependencies
	cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm ci

dev:            ## Run API (8000) and UI (5173) with hot reload
	cd backend && .venv/bin/uvicorn app.main:app_factory --factory --reload --port 8000 & \
	cd frontend && npm run dev

test:           ## All tests
	cd backend && .venv/bin/pytest -q
	cd frontend && npm test

lint:           ## Static checks
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy
	cd frontend && npm run typecheck

fmt:            ## Auto-format
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
	cd infrastructure/terraform && terraform fmt -recursive

ingest:         ## Sync the knowledge base into Pinecone
	cd backend && .venv/bin/python -m scripts.ingest

up:             ## Full local stack in Docker
	docker compose up --build

down:
	docker compose down -v

load:           ## k6 load test against $BASE_URL (default http://localhost:8000)
	k6 run -e BASE_URL=$${BASE_URL:-http://localhost:8000} tests/load/chat.js
