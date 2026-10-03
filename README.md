# Market-Business-App

## Start Here

This repository contains planning documents, source artifacts, and a local FastAPI application with health and receipt workflows. Use [the current implementation slice](plan/03-current-slice.md) to find the next bounded task. Do not infer the active task from capability numbering or the first unchecked item in a later capability.

The governing documents, in precedence order, are the approved signed readiness decision, [the implementation overview](plan/00-overview.md), [the MVP roadmap](plan/01-mvp-roadmap.md), then the active capability document. Source workbooks and historical prompts provide evidence but do not override those decisions. See [the implementation-readiness gate](plan/02-implementation-readiness.md) before using real business data, enabling live providers, or promoting a release.

The application targets Python 3.14. Its runtime image uses `python:3.14-slim-trixie`, which currently resolves to official Python 3.14.7; Python 3.14.8 is released upstream but its official Docker tag is not published yet. Compatibility with earlier Python versions is not a requirement. PostgreSQL and Redis use pinned PostgreSQL 18.6 and Redis 8.10.2 images. The production runtime image excludes tests and developer tools; tests run on the host or the dedicated test target. The older Devin prompt under `support/` is retained as historical context; its Java/Spring/React/Kubernetes stack is superseded by the approved plan.

## Local Development

Application code follows domain/service/repository layering. See [the architecture
and refactor evidence](docs/architecture.md) for ownership rules, the module layout,
compatibility imports, and validation results.

Use Python 3.14 for host development. The Docker app tracks the latest Python 3.14 patch in the official Trixie image. Host workflow (using [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --frozen --python 3.14
uv run --frozen ruff check src tests
uv run --frozen mypy src tests
```

Docker Compose (web, postgres, redis, celery-worker, celery-beat) — verified 2026-10-01 with Docker Desktop 29.8.1 on Windows 11 (see [the Windows Docker guide](user-docs/Docker_Windows11_Installation_Guide.md)):

```bash
cp .env.example .env
docker compose config
docker compose up --build -d postgres redis
docker compose run --rm --build migrate
docker compose up --build -d web celery-worker celery-beat
docker compose run --rm --build test
docker compose run --rm --build test-migrations-postgres
docker compose logs -f web
docker compose down
```

PostgreSQL is the only supported runtime and database-test engine. The `runtime` image excludes tests/developer tools; `test` includes PostgreSQL 18 clients, Chromium, tests, plan settings catalog, and synthetic support tools. Private receipt directories are excluded from build context. No Node installation is required.

Compose builds the connection URL from `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`; change the example password before any real-data deployment. An optional `DATABASE_URL` overrides those fields and must match the server credentials. Split fields accept literal special characters; full URLs need percent-encoded credentials. Alembic uses the same configuration, with explicit Config URLs taking precedence.

For the fast local edit/test loop, build the tooling image once, then run against current working files:

```bash
docker compose build test
docker compose run --rm test-dev pytest tests/test_receipt_approval.py -q
docker compose run --rm test-dev ruff check src tests
docker compose run --rm test-dev mypy src tests
docker compose run --rm test-dev
```

`test-dev` mounts source, tests, migrations, plan and selected synthetic support files read-only, so ordinary edits need no image rebuild. It runs as the non-root test user, uses private temporary work and a separate tool-cache volume, and never mounts the application database/files or private receipts. It is a development profile: naming it in `docker compose run` enables it, but normal `docker compose up` does not start it. Test results still come from the real migrated PostgreSQL service; caching does not skip tests or weaken constraints.

Changes to `pyproject.toml`, `uv.lock`, or `Dockerfile` require `docker compose build test`. The development entrypoint compares those files to the image's build-time copies and refuses to run if they differ; it never silently installs or changes dependencies. Do not use `uv run` or `uv sync` inside the mounted service; invoke the installed `pytest`, `ruff`, or `mypy` directly. Use `pytest -k <expression>` or explicit test paths for focused development checks, but always run the full gate before declaring completion.

CI/release verification stays self-contained and unmounted: `docker compose run --rm --build test`. That service tests files copied into the image, so source/test/migration changes require rebuilding it. A passing `test-dev` run is working-tree evidence, not candidate-image certification. Both paths create and clean up random isolated PostgreSQL databases, never the application database. The dedicated test role needs CREATE DATABASE; missing database configuration fails rather than silently skipping.

For VS Code host debugging, start `docker compose up -d postgres redis postgres-migration-test`, then set the host process's environment (Compose service names do not resolve on the host):

```bash
export DATABASE_HOST=127.0.0.1 DATABASE_PORT=5432 DATABASE_NAME=mbs
export DATABASE_USER=mbs DATABASE_PASSWORD=change-me
export REDIS_URL=redis://127.0.0.1:6379/0
export RECEIPT_STORAGE_PATH=data/receipts
uv run --frozen uvicorn mbs.main:app --port 8001
```

Match credentials/ports to your local configuration; use PowerShell `$env:NAME='value'` equivalents on Windows. If `DATABASE_URL` is set, unset it or point it at the host's loopback address. `MBS_POSTGRES_PORT` and `MBS_TEST_POSTGRES_PORT` control loopback-only published ports (defaults 5432 and 55432); choose unused ports if occupied. This host example is for database/API debugging, not an end-to-end OCR stack: Redis is not published by default, and the container worker's named file volume is not the host's `data/receipts`. For host upload/worker debugging, use a development override with a loopback Redis port and a shared protected-file bind mount, or run both web and worker on the host with the same environment/storage root and installed OCR binaries. Prefer the complete Compose stack for end-to-end workflows. Host full tests also require matching PostgreSQL clients, Chromium, and `MBS_TEST_DATABASE_URL` for the dedicated test database.

Keep SQLAlchemy/Alembic and core services generic. **A different database URL is not a compatibility guarantee:** filtered unique indexes, case folding, locks, transactional DDL, JSON semantics and backup tools need backend adapters and a new test matrix. See the [all-stage PostgreSQL contract](plan/00-overview.md#postgresql-contract-all-stages). Never use `docker compose down -v` as routine migration recovery; it deletes application data. Production must use its separate gated profile without reload/source mounts/test services/example passwords.

The test-case manifest schema is at [plan/test-case-manifest.csv](plan/test-case-manifest.csv). It is not complete until every required source case and MVP 1 criterion has a verified mapping and the readiness gate is approved.