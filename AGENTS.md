# Repository Agent Instructions

These instructions apply to any coding agent working in this repository, regardless of editor, model, or agent product.

## Plan Work

- When creating, extending, reviewing, or implementing a plan, load `.agents/skills/plan-driven-development/SKILL.md`.
- Keep ordinary coding tasks free of plan-specific workflow unless the user asks for plan work.

## Implementation Standards

- Search for the owning implementation and nearby tests before editing.
- Add or update focused tests for every behavior change.
- Run the narrowest relevant test first, then the repository's required lint, type-check, and full test commands before declaring completion.
- Do not claim a command passed unless it was actually run. Report unavailable tools, skipped checks, warnings, and unrelated failures.
- Use synthetic data, mocks, and provider sandboxes. Never commit secrets, tokens, customer data, production exports, or local environment files.
- Model synthetic fixtures on reality: when a fixture stands in for something the business actually receives, consult the real examples in the local untracked `receipts/` directory for layout, formats, and edge cases, then reproduce that shape with invented values. Never copy a real value, filename, image, or expected-result entry into the repository, a test, CI, a log, or a chat message.
- Keep public behavior and established architecture stable unless the active plan step requires a change.

## Review Gate (D-00)

- After a slice passes validation, critically review all code, tests, and migrations it touched before marking it complete or moving on: real entry-point wiring, tests that prove their claims, security, plan/code/migration consistency (including PostgreSQL), dead or duplicate code, and concurrency/idempotency.
- Fix every finding, re-run validation, and record findings and fixes in the slice evidence. Stop and ask when a finding has no clear answer.
- Never push, rewrite git history, approve an owner decision, or promote production without explicit user approval. See D-00 in `plan/04-go-no-go.md`.

