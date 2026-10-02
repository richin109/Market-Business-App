# MBS Coding Instructions

- For creating, extending, reviewing, or implementing a plan, load `.agents/skills/plan-driven-development/SKILL.md`.
- For ordinary coding tasks, keep changes small, preserve the existing architecture, add focused tests, and run the repository's available lint and type checks.
- Private data, including images and PDFs, may be used for local development and tests. Keep private inputs and generated outputs in gitignored locations, add ignore rules as needed, and verify they are not tracked. Never commit or push private data, secrets, production exports, or local environment files to GitLab or another remote.
- Run relevant private-data tests locally when inputs are available, even though those inputs are gitignored. Keep committed fixtures synthetic and CI independent of private files. Do not expose private contents in shared logs, artifacts, or chat, or upload them to external providers without explicit approval.
- Model committed synthetic fixtures on the real examples in the local untracked `receipts/` directory: copy the layout, formats, and edge cases, never the values, filenames, images, or expected results.
- Do not claim a command passed unless it was actually run; report unavailable tools and skipped checks.
