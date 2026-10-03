# Layered Python Architecture

## Issues

The original routes mixed HTTP handling with queries, row mutations, transactions,
audit creation, gallery policy, and receipt review assembly. Several functional
modules also mixed pure rules, persistence, and external OCR/image/file tooling.
The gallery route duplicated an existing service implementation. The single model
module was declarative but grouped unrelated schema contexts.

Applied corrections cover all maintained application modules under `src/mbs`.
Historical support tools, migrations, templates, product requirements, and private
receipt inputs were not redesigned. Test database setup intentionally remains
database-aware. PostgreSQL is still the sole certified database backend.

The Docker application runtime targets Python 3.14. The project minimum remains
Python 3.12, and compatibility below 3.12 is not required.

## Corrected Code

- Routes validate transport inputs, apply authentication/CSRF dependencies, map
  application errors to HTTP, and delegate. They do not build queries or operate on
  database sessions. Multipart parsing and bounded request buffering stay here.
- Services orchestrate business decisions and atomic workflows through
  repositories, pure domain rules, and infrastructure adapters. They contain no
  SQL statements or HTTP framework dependencies. Existing ORM records remain the
  persistence-facing data objects; service decisions may update their state within
  the caller's unit of work, but query and transaction execution belongs to
  repositories. This deliberately avoids a second, duplicative entity model.
- Domain modules contain pure value objects, normalization, signatures, merchant
  parsers, classification, segmentation, reconciliation, units, and small policies.
- Repositories own SQLAlchemy queries, writes, row locks, savepoints, transactional
  scopes, and backend-specific database operations. Their callers determine policy;
  repositories do not decide whether to approve, merge, reroute, or post a receipt.
- Models contain only declarations, defaults, indexes, and constraints. All 29
  declarations retain the same metadata and public `mbs.models` import path.
- Infrastructure owns Pillow/OpenCV, PyMuPDF/Tesseract, scanners, protected files,
  hashing adapters, and broker/CLI composition. No provider or schema was replaced.

For example, receipt detail now follows this path:

```python
try:
    return receipt_response(session, receipt_pk)
except NotFoundError as error:
    raise HTTPException(status_code=404, detail=str(error)) from error
```

The response service delegates the active-receipt, line, store-item, and source
queries to `ReceiptReadRepository`; the router never runs SQL.

The original functional import paths are compatibility facades, not alternate
implementations. Patch/injection points belong to their owning implementation;
authentication tests now patch `mbs.services.auth`, which owns throttle state.
The router dispatch callback and task `SessionLocal` injection points remain intact.

## New File Structure

```text
src/mbs/
  domain/          pure receipt, item, store, auth, settings, and media rules
  services/        business workflows, commands, reads, and review assembly
  repositories/   SQLAlchemy persistence, locks, transactions, and caches
  models/         schema declarations grouped by bounded context
  infrastructure/ PDF/OCR, image, scanner, hashing, and file adapters
  routers/        FastAPI transport validation and delegation
  receipts/       compatibility facades, Celery task wiring, dispatch adapter
  main.py         application composition and security middleware
  cli.py          interactive administrative CLI adapter
  backup.py       backup filesystem/process orchestration and CLI adapter
```

Receipt work is divided into intake, manual entry, approvals, lifecycle, source
association, correction inputs/state/review/holds, review reads, image candidates,
uploads/batches, extraction, processing, and outbox publication. Item work separates
identity, mapping history, metadata, suggestions, commands, reads, and galleries.

## Summary

Verification on the rebuilt, unmounted candidate `sha256:5dc268886a937df775ea956b3256b3c157f`:

| Command | Result |
| --- | --- |
| `docker compose run --rm test` | 237 passed, 2 skipped |
| `docker compose run --rm test ruff check src tests` | Passed |
| `docker compose run --rm test mypy src tests` | Passed, 179 files |
| `docker compose run --rm --build test-migrations-postgres` | 1 passed, no skips |
| Editor diagnostics | No errors |

The architecture regression suite checks every production query's owner, every
service's framework independence, pure domain dependencies, every API router's
lack of session operations, declarative models, compatibility aliases, gallery
rules, ranking, configuration, and retention policy.

Critical review preserved parent/line lock ordering, refreshed identity reads,
savepoint recovery, unique-constraint fallback, append-only correction history,
raw/source evidence, forward-only mappings, primary-image constraints, source-line
replay checks, malware audit commits, commit-before-dispatch ordering, worker lease
fencing, and backup snapshot/count consistency. Focused tests caught and repairs
resolved moved-helper imports, SQLAlchemy row conversion, query typing, audit-string
formatting, error-handler typing, and explicit re-exports. The existing PyMuPDF
untyped-call exception follows only its relocated infrastructure adapters.

No migration, credential, private-data fixture, production promotion, commit, or
push is included. The active product queue and readiness gates remain unchanged.
Private-corpus checks use ignored local logs and read-only inputs; synthetic
candidate results are not a private-corpus accuracy certification.