# Market-Business-App

## Start Here

This repository contains planning documents, source artifacts, and the local development foundation (health endpoint only). Use [the current implementation slice](plan/03-current-slice.md) to find the next bounded task. Do not infer the active task from capability numbering or the first unchecked item in a later capability.

The governing documents, in precedence order, are the approved signed readiness decision, [the implementation overview](plan/00-overview.md), [the MVP roadmap](plan/01-mvp-roadmap.md), then the active capability document. Source workbooks and historical prompts provide evidence but do not override those decisions. See [the implementation-readiness gate](plan/02-implementation-readiness.md) before using real business data, enabling live providers, or promoting a release.

The confirmed implementation stack is Python 3.12, FastAPI, Jinja2/HTMX, PostgreSQL, Redis/Celery, and Docker Compose. The older Devin prompt under `support/` is retained as historical context; its Java/Spring/React/Kubernetes stack is superseded by the approved plan.

## Local Development

Verified on the host (Python 3.12, [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --frozen --python 3.12
uv run --frozen pytest
uv run --frozen ruff check src tests
uv run --frozen mypy src tests
uv run --frozen uvicorn mbs.main:app --port 8000   # then GET http://127.0.0.1:8000/health
```

Docker Compose (web, postgres, redis, celery-worker, celery-beat) — verified 2026-09-30 with Docker Desktop 29.8.1 on Windows 11 (see [the Windows Docker guide](user-docs/Docker_Windows11_Installation_Guide.md)):

```bash
cp .env.example .env
docker compose config
docker compose up --build -d
docker compose exec web pytest
docker compose exec web ruff check src tests
docker compose exec web mypy src tests
docker compose logs -f web
docker compose down
```

The test-case manifest schema is at [plan/test-case-manifest.csv](plan/test-case-manifest.csv). It is not complete until every required source case and MVP 1 criterion has a verified mapping and the readiness gate is approved.