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
- Keep public behavior and established architecture stable unless the active plan step requires a change.

