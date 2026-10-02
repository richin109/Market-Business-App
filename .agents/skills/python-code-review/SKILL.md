---
name: python-code-review
description: "Senior Python review/refactoring. Use for python_code_review, code_review, review_python, execution_plan_review, or refactor_python; checks plan alignment, structure, maintainability, risks, and applies focused fixes."
argument-hint: "Provide Python code, a file/path to review, and optionally an execution-plan stage"
---

# Python Code Review

Review Python code against its execution-plan stage when available, report actionable risks, provide corrected code, and apply clear, focused fixes to workspace files.

## Inputs

- `code` (required): Code in the prompt, editor selection, or workspace path.
- `execution_plan_stage` (optional): Stage to validate. If omitted, inspect only the nearest relevant plan context; never invent a stage.

If the target is missing, report what is needed in the final recommendations; do not pause an active review for clarification.

## Procedure

1. Inspect the target, owning code, relevant call sites, nearby tests, and only the plan context needed. For project-wide reviews, cover all maintained Python source and tests; exclude virtual environments, caches, generated and vendored files unless requested. Work by module and track coverage.
2. Check stage alignment: scope creep, missing responsibilities, misplaced logic, and deviations. If no applicable plan exists, say alignment was not assessed.
3. Assess correctness, security, errors, side effects, data handling, logging, naming, readability, duplication, testability, coupling, and structure. Flag oversized classes, mixed responsibilities, long functions, or poor module boundaries based on cohesion, not line-count thresholds.
4. Report concrete, located findings in severity order. Explain issue, impact, and fix; prioritize correctness/security and omit speculative style nits.
5. Provide corrected code. For workspace code, apply the smallest clear fixes, add focused tests for behavior changes, and run narrow validation. For chat-only code, return snippets and do not claim file edits. Never pause to clarify: do not guess on ambiguous behavior, unresolved plan/product decisions, or broad architecture; continue other clear work and report blockers at the end.
6. Report structural changes, recommendations, validation commands/results, and remaining gaps accurately.

## Output

### Overview
Code health and plan alignment, or state that alignment was not assessed.

### Findings
Severity-ordered list. For each: **Title** (severity when useful), **Issue** (with location), **Risk**, **Fix strategy**, and **Corrected code** (snippet or applied-change reference). State when there are no findings.

### Refactored Structure Summary
Describe the new class/module layout or state that none was needed.

### Final Recommendations
Next steps, validation results/gaps, and unresolved decisions.