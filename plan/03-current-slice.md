# Current Implementation Slice

Status: **in progress — receipt domain slice implemented through in-memory review/retrieval; database/API/Docker validation remains pending (U-1 in [04-go-no-go.md](04-go-no-go.md))**.

Evidence recorded 2026-09-30 (host, Python 3.12.10, uv-managed environment from `uv.lock`): `pytest` 24 passed; `ruff check src tests` passed; `mypy src tests` (strict) passed; HTTP `GET /health` returned `{"status":"ok"}` from uvicorn. Receipt tests cover normalization, raw OCR snapshots and metadata, upload validation, exact and canonical-ID deduplication, in-memory retrieval, immutable review dispositions, and remembered-rule matching. Not run: `docker compose` commands below (Docker not installed).

## Active Task — MVP 1 Receipt Normalization Slice

Establish the first receipt-only domain slice with synthetic data and a mocked OCR boundary. This remains local development work and is permitted under the conditional-go status in [the implementation-readiness gate](02-implementation-readiness.md).

**Scope**
- Define a provider-neutral `OCREngine` boundary for mocked and future Document AI implementations.
- Normalize mocked OCR headers and line items into immutable typed receipt data, preserving raw date/time values and OCR metadata.
- Build the composite `Receipt_ID` from store, full ISO date, canonical time, and transaction number, with exact and canonical-ID duplicate guards.
- Validate synthetic upload signatures and source hashes, then save accepted receipts to an injectable in-memory repository.
- Classify merchandise independently from business dispositions; support immutable review updates and remembered-rule matching.

**Dependencies**
- The Python stack and local services are confirmed in [the implementation overview](00-overview.md) and [Capability 11](capabilities/11-deployment-infrastructure.md).
- Verify Docker Desktop or Docker Engine with Compose is available; install it if needed, as called out in Capability 11.1. This prerequisite is not yet confirmed.
- No Square, Meta, or Google credentials, real receipts, or production infrastructure are required.

**Out of scope**
- Google Document AI calls, PostgreSQL/Alembic persistence, HTTP upload/read APIs, authentication workflows, Celery orchestration, protected file storage, live provider calls, real data, and production deployment.
- Any decision about market-specific timezone behavior, MVP 2 price/session allocation, or settlement state transitions.

**Acceptance evidence**
- Synthetic mocked OCR normalizes to typed receipt header and item data.
- Raw source date/time values are retained while canonical ISO values are validated.
- Receipt identity is stable and Decimal totals are used; mismatched line totals are flagged.
- Focused receipt tests, the full test suite, Ruff, and mypy complete successfully.
- No real receipt files or live providers are used.
- The 24-test suite, Ruff, and mypy pass; Docker remains unavailable on the host.

**Validation commands used for this slice**
- `uv run --frozen pytest tests/test_receipt_ocr.py -q`
- `uv run --frozen pytest`
- `uv run --frozen ruff check src tests`
- `uv run --frozen mypy src tests`

The foundation's Docker validation remains pending: `docker compose config` cannot run because Docker is not installed on this host.

These are target commands for the slice, not commands already verified in this repository. Record any necessary command adjustment in the README and Copilot instructions when the scaffold is implemented.

## Owner Decisions Required Before Affected Work

These do not block the local foundation, but must be resolved and recorded before implementing the affected MVP 2 behavior.

| Decision | Clarification required | Affected plans |
|---|---|---|
| Timezone authority | Confirm whether each market has its own IANA timezone, or whether the configured business timezone is authoritative for operating-hour interpretation and business-date assignment. Preserve full-date historical attribution either way. | `00-overview.md`, Capabilities 5 and 14, MVP 2 |
| Market-session price and availability | Confirm the MVP 2 source of customer-facing price, the permitted scope of a session override, and the contract for reserving/committing/reversing/disposition of available quantity before full inventory ships. Keep Square order amounts authoritative for Square sales. | Capabilities 4, 14, and 16; MVP 2 |
| Sale and closeout states | Record one transition table distinguishing provider-staged/pending, accepted, import exception, operationally closed, and settlement-reconciled states, including which totals each state may affect. | Capabilities 3, 14, and 16; Capability 10 sales-mvp |

Do not choose these rules by inference. Ask the business owner and update the governing plan before coding them.

## After This Slice

Next: implement the database-backed receipt upload/read boundary with reviewed SQLAlchemy models, Alembic migrations, and focused API tests. Real OCR remains blocked until the readiness approvals are complete.