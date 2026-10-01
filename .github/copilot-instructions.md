# MBS Coding Instructions

- For creating, extending, reviewing, or implementing a plan, load `.agents/skills/plan-driven-development/SKILL.md`.
- For ordinary coding tasks, keep changes small, preserve the existing architecture, add focused tests, and run the repository's available lint and type checks.
- Use synthetic data and mocks. Never commit secrets, customer data, production exports, or local environment files.
- Model synthetic fixtures on the real examples in the local untracked `receipts/` directory: copy the layout, formats, and edge cases, never the values, filenames, images, or expected results.
- Do not claim a command passed unless it was actually run; report unavailable tools and skipped checks.
