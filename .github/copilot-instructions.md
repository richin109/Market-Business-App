# MBS Coding Instructions

## Plan-Driven Workflow

- Resolve requirement conflicts using the precedence in `plan/02-implementation-readiness.md`: approved signed readiness decision, then `plan/00-overview.md`, then `plan/01-mvp-roadmap.md`, then the active file under `plan/capabilities/`, then source documents and workbooks. Stop and surface a conflict only when that precedence does not resolve it.
- Start with `plan/03-current-slice.md`. Implement only its named task; do not infer priority from capability numbering or select a later unchecked checkbox. If that file is missing, stale, blocked, or lacks acceptance evidence and a validation command, stop and report the gap.
- Before implementation, identify the current capability, the next unchecked and unblocked step, its acceptance criteria, dependencies, exclusions, and the smallest validation that can prove it works. Link applicable entries in `plan/test-case-manifest.csv`.
- Implement one coherent, runnable slice at a time. Do not build later roadmap items, speculative abstractions, or parallel versions of a domain service unless the active step requires them.
- Preserve the architecture and cross-cutting rules in `plan/00-overview.md`. Do not silently substitute frameworks, providers, data ownership rules, or deployment choices.
- Search for the owning implementation and nearby tests before editing. Reuse established project patterns and shared domain services.

## Evidence Over Guessing

- Never invent requirements, API behavior, schema details, credentials, business rules, or completion status. Record an explicit assumption when it is low risk and reversible; ask the user when the choice affects money, tax, security, provider behavior, or irreversible data design.
- Use synthetic data, mocks, and provider sandboxes during development. Never use real business data unless the implementation-readiness gate permits it.
- Steps marked `User Input Required` are blockers for the agent. Explain the exact user action needed and continue only with independent unblocked work.

## Definition of Done

- Add or update focused tests for every behavior change. Run the narrowest relevant tests first, then the repository's required lint, type-check, and test commands before declaring a slice complete.
- Do not claim a command passed unless it was run successfully. Report unavailable tools, skipped checks, and unrelated failures clearly.
- Check a plan implementation step only after its code and required validation pass. Check a feature or capability only when every child checkbox is complete; never mark `User Input Required` work complete for the user.
- Do not mark the active-slice task or a test-manifest row complete without recording the passing validation result and evidence. Do not claim workbook coverage from an unverified structural check.
- Keep plan documents synchronized with confirmed implementation decisions, but do not rewrite requirements merely to match the code.

## Change Discipline

- Keep changes small, reviewable, and reversible. Avoid unrelated refactors, dependency additions, generated churn, and broad formatting changes.
- Never commit secrets, tokens, customer data, production exports, or local environment files. Provide `.env.example` entries with safe placeholders when configuration is required.
- At the end of each slice, summarize what changed, validation results, remaining assumptions, and the exact next unchecked plan step.

## Current Toolchain Status

- The plan specifies Python 3.12, FastAPI, Ruff, mypy, pytest, and Docker Compose. Until the project scaffold defines and verifies concrete commands, do not invent or report setup, migration, lint, type-check, or test commands as passing.
- Use synthetic data and mocked providers for local work. Real receipt data, live Google/Square/Meta calls, and production promotion remain blocked by the applicable readiness approvals and release profile.
