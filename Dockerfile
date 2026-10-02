FROM python:3.14-slim-trixie AS ocr-base

# pg_dump/pg_restore must match the server major version (postgres:18), so use the PGDG client.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tesseract-ocr tesseract-ocr-eng \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

FROM ocr-base AS dependencies

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    RUFF_CACHE_DIR=/tmp/ruff-cache \
    MYPY_CACHE_DIR=/tmp/mypy-cache \
    PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM dependencies AS build
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

FROM dependencies AS test-tools
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN uv sync --frozen --no-install-project && playwright install --with-deps chromium

FROM test-tools AS test
COPY pyproject.toml uv.lock Dockerfile /opt/mbs-test-config/
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN uv sync --frozen
COPY tests ./tests
COPY plan/*.md plan/*.csv ./plan/
COPY plan/capabilities ./plan/capabilities
COPY support/__init__.py support/review_receipts.py support/receipt_review.html ./support/
RUN useradd --create-home --uid 1000 mbs \
    && install -d -o mbs -g mbs /tmp/mbs-test-cache
USER mbs
CMD ["pytest"]

FROM ocr-base AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app/src ./src
COPY --from=build /app/alembic.ini ./alembic.ini
COPY --from=build /app/alembic ./alembic

RUN useradd --create-home --uid 1000 mbs \
    && mkdir -p /var/lib/mbs/receipts \
    && chown -R mbs:mbs /var/lib/mbs
USER mbs

EXPOSE 8000
CMD ["uvicorn", "mbs.main:app", "--host", "0.0.0.0", "--port", "8000"]
