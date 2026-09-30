---
name: plan-driven-development
description: "Use when creating, extending, or implementing a repository plan; requires checkbox-based steps, evidence-backed completion, validation commands, and reporting the next unchecked step."
---

# Plan-Driven Development

Use this workflow only when the user asks to create, extend, review, or implement a plan or roadmap.

## Before Editing

1. Read `plan/03-current-slice.md`.
2. Identify the active capability, next unchecked and unblocked step, acceptance criteria, dependencies, exclusions, and smallest validation.
3. Resolve conflicts in this order: approved readiness decision, `plan/00-overview.md`, `plan/01-mvp-roadmap.md`, active capability file, then source artifacts.
4. Search for the owning implementation and nearby tests.
5. Stop and report if the active slice is missing, stale, blocked, or lacks acceptance evidence and a validation command.

For this repository specifically:

- Link applicable rows in `plan/test-case-manifest.csv`.
- Preserve the Python-native FastAPI, Jinja2/HTMX, PostgreSQL, Redis/Celery, and Docker Compose architecture in `plan/00-overview.md`.
- Do not substitute the historical Java/Spring/React/Kubernetes stack from `support/`.
- Treat real Google, Square, Meta, receipt, and production work as blocked by the readiness gate unless its approvals are recorded.

## Plan Checkboxes

- Write every actionable plan step as `- [ ]` with a concrete outcome.
- Include a focused validation command or test when practical.
- Change `- [ ]` to `- [x]` only after the implementation exists and required validation passes.
- Record validation evidence beside the checked item or in the active-slice evidence section.
- Leave partially implemented, blocked, approval-required, credential-required, and user-input steps unchecked.
- Check a parent feature or capability only after every required child step is checked.
- Do not rewrite requirements merely to make the code appear complete.

## Implementation

- Implement one small, runnable, reversible slice at a time.
- Use synthetic data, mocks, and provider sandboxes unless the readiness gate explicitly permits real data.
- Add or update focused tests for every behavior change.
- Run the narrowest relevant test first, followed by repository lint, type-check, and full test commands.
- Do not claim a command passed unless it was actually run. Report unavailable tools, skipped checks, warnings, and unrelated failures.
- Keep the plan synchronized with confirmed implementation decisions.

Repository validation currently verified on the host uses Python 3.12 and uv:

- `uv run --frozen pytest`
- `uv run --frozen ruff check src tests`
- `uv run --frozen mypy src tests`

Docker Compose commands and migration commands are not verified until their prerequisites and implementations exist.

## Completion Report

Report:

1. What changed and which checkboxes were completed.
2. Validation commands and actual results.
3. Remaining assumptions, blockers, and unchecked work.
4. The exact next unchecked plan step.
