# Current Implementation Slice

Status: **queued; application code has not started**.

## Active Task — MVP 1 Local Development Foundation

Establish a runnable local Python application and repeatable development/test loop. This is local foundation work only; it is permitted under the conditional-go status in [the implementation-readiness gate](02-implementation-readiness.md).

**Scope**
- Declare the Python 3.12 runtime and planned dependencies in `pyproject.toml`, including FastAPI, pytest, Ruff, and mypy; add a reproducible dependency lock file.
- Create the minimal `src/mbs/` application with a health endpoint and one focused test.
- Add the MVP 1 local Docker Compose services from Capability 11.1: web, PostgreSQL, Redis, Celery worker, and Celery beat. Keep credentials as safe placeholders; no provider credentials are needed for this slice.
- Add documented commands for starting/stopping/logging, migrations, tests, lint, and type checking only after their implementations exist.

**Dependencies**
- The Python stack and local services are confirmed in [the implementation overview](00-overview.md) and [Capability 11](capabilities/11-deployment-infrastructure.md).
- Verify Docker Desktop or Docker Engine with Compose is available; install it if needed, as called out in Capability 11.1. This prerequisite is not yet confirmed.
- No Square, Meta, or Google credentials, real receipts, or production infrastructure are required.

**Out of scope**
- Receipt upload/OCR, authentication workflows, business schemas/migrations, live provider calls, real data, and production deployment.
- Any decision about market-specific timezone behavior, MVP 2 price/session allocation, or settlement state transitions.

**Acceptance evidence**
- A fresh local environment can build and start the services using the documented commands.
- The health endpoint returns a successful response.
- The focused health test, Ruff, and mypy complete successfully in the project environment.
- The image contains no real credentials and no live provider is called.

**Validation commands to establish in this slice**
- `docker compose config`
- `docker compose up --build -d`
- `docker compose exec web pytest`
- `docker compose exec web ruff check src tests`
- `docker compose exec web mypy src`
- An HTTP smoke check against the documented health endpoint.

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

Next: implement the first receipt-only vertical slice selected from Capabilities 1 and 2, using mocked OCR and synthetic receipt files. Select its precise feature steps and focused validation after the local foundation is verified. Real OCR remains blocked until the readiness approvals are complete.