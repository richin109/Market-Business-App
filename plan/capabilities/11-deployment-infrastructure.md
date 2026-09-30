# Capability 11: Deployment & Infrastructure

- [ ] **Capability complete** (all features below checked)

**Decision:** Development runs on this laptop now. Production later runs on a self-hosted **Proxmox VM**, not Kubernetes — simpler operationally and appropriately scaled for this application's load. The blueprint's original Kubernetes/Helm production design (§11.2) is not used; it's noted below only for context in case scale later justifies revisiting it.

## Feature 11.1 — Local Development (this laptop)
- [ ] Feature complete
- [ ] `docker-compose.yml` with services: `web` (FastAPI + Jinja2/HTMX app, hot reload), `postgres` (15-alpine, persistent volume), `redis` (7-alpine, Celery broker/result backend), `celery-worker`, `celery-beat`. No separate `react-frontend`/Node service — the web UI is served by the same FastAPI app.
- [ ] `.env.example` documents Receipt MVP required variables (`DATABASE_URL`, `REDIS_URL`, persistent receipt-file store path, Google Document AI credentials/processor ID/region, JWT secret); Tesseract settings are optional fallback, and Square/Meta credentials are optional future-capability placeholders only.
- [ ] Generate and commit a version-pinned Tailwind CSS static asset with the standalone CLI; serve it locally from the web/reverse-proxy layer in production. The production content-security policy must not require Tailwind CDN access.
- [ ] 🧑‍💻 Install Docker Desktop (or Docker Engine + Compose) on this laptop if not already installed: https://docs.docker.com/get-docker/
- [ ] `make`/script targets (or a simple `run.sh`) for `up`, `down`, `logs`, `migrate`, `test` to keep local workflow one-command simple.
- [ ] The local `migrate` target applies version-controlled Alembic revisions; schema changes made during development are captured in a new revision rather than left as manual database edits. The test target applies migrations when preparing its database.

## Feature 11.2 — Production Target: Proxmox VM
- [ ] Feature complete
- [ ] 🧑‍💻 Provision a Linux VM (Debian or Ubuntu Server LTS recommended) inside Proxmox with enough disk for Postgres data + receipt image storage; Proxmox docs: https://pve.proxmox.com/pve-docs/
- [ ] 🧑‍💻 Assign the VM a static IP (or DHCP reservation) on your network and decide whether it's reachable only on your LAN or exposed externally (affects the reverse-proxy/TLS step below).
- [ ] Install Docker Engine + Docker Compose plugin on the VM (same `docker-compose.yml` used in dev, with production env values).
- [ ] Add a reverse proxy (Caddy recommended for automatic HTTPS with minimal config, or Nginx if you already run Nginx elsewhere): Caddy docs https://caddyserver.com/docs/ — terminates TLS and proxies to the FastAPI `web` service.
- [ ] 🧑‍💻 If exposing outside the LAN, either configure port-forwarding + a DNS record you control, or use a tunnel service (e.g., Cloudflare Tunnel) instead of opening inbound ports directly: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- [ ] Production recovery targets are RPO <= 24 hours and RTO <= 8 hours. Schedule encrypted database and receipt-file backups at least nightly, and run a timed restore test proving both targets; receipt images are business data and are not covered by a database-only backup.
- [ ] Document the encrypted backup destination, retention, encryption-key owner and recovery procedure, and restore-test owner before storing real receipts. Complete the applicable real-data approvals in [the implementation-readiness gate](../02-implementation-readiness.md).
- [ ] Secrets (DB credentials, JWT secret, Google/Square/Meta WhatsApp credentials) stored in an `.env` file with restricted file permissions on the VM, or a secrets manager if one is already in use; never committed to source control.

## Feature 11.3 — CI/CD Pipeline
- [ ] Feature complete
- [ ] GitHub Actions: Lint (`ruff`, `mypy`) → run the MVP-specific test profile required by Capability 10 → Build a versioned Docker image → Deploy only after that MVP's release gate passes. MVP 7 includes all 110 source regression cases; MVP 8 runs the full MBS suite.
- [ ] Deploy stage: back up database and file store, pull the versioned image, run exactly one Alembic migration job, deploy web/worker services only after migration success, then run health and workflow smoke tests. Do not run migrations independently in every web/worker startup.
- [ ] Define rollback by migration compatibility: roll application images back only when the schema remains compatible; otherwise restore database and file backups under the RPO/RTO procedure. Document failed-migration and failed-smoke-test recovery.
- [ ] 🧑‍💻 Add repository secrets in GitHub for deploy SSH key/host and any registry credentials: repo Settings → Secrets and variables → Actions.

## Feature 11.4 — Future Scaling Option (not built now)
- [ ] Feature complete (or explicitly marked "not pursuing")
- [ ] If usage grows beyond a single VM (multiple concurrent users, heavier OCR/import volume), revisit Kubernetes (Helm charts) as in the original blueprint §11.2 — deferred until there's a concrete need.

## Feature 11.5 — Receipt MVP Early Deployment

- [ ] Feature complete
- [ ] Deploy the receipt-only vertical slice with Docker Compose: web app, Postgres, Redis/Celery worker, Google Document AI integration, and persistent protected receipt-file storage. Do not require Square, WhatsApp, or downstream MBS services to be configured.
- [ ] Provide a one-time secure first-ADMIN bootstrap command after migrations; require the operator to enter credentials locally, create no default password, and document an audited recovery/reset path. Provide authenticated manager upload/review UI, health check, and smoke test proving saved OCR data and receipt rows survive an app/container restart without another OCR call.
- [ ] For initial use, restrict access to the laptop/LAN; if accessed beyond the trusted LAN, require HTTPS, secure authentication, and firewall/reverse-proxy configuration.
- [ ] Complete automated Postgres and receipt-file backup plus a tested restore before storing real receipts; keep uploads outside ephemeral container filesystems.
- [ ] Promote the same versioned Docker images/configuration from this internal MVP to the Proxmox target when it is ready; add later capabilities in subsequent releases.
