# Market-Business-App

## Start Here

This repository currently contains planning documents and source artifacts; application code has not started. Use [the current implementation slice](plan/03-current-slice.md) to find the next bounded task. Do not infer the active task from capability numbering or the first unchecked item in a later capability.

The governing documents, in precedence order, are the approved signed readiness decision, [the implementation overview](plan/00-overview.md), [the MVP roadmap](plan/01-mvp-roadmap.md), then the active capability document. Source workbooks and historical prompts provide evidence but do not override those decisions. See [the implementation-readiness gate](plan/02-implementation-readiness.md) before using real business data, enabling live providers, or promoting a release.

The confirmed implementation stack is Python 3.12, FastAPI, Jinja2/HTMX, PostgreSQL, Redis/Celery, and Docker Compose. The older Devin prompt under `support/` is retained as historical context; its Java/Spring/React/Kubernetes stack is superseded by the approved plan.

The test-case manifest schema is at [plan/test-case-manifest.csv](plan/test-case-manifest.csv). It is not complete until every required source case and MVP 1 criterion has a verified mapping and the readiness gate is approved.