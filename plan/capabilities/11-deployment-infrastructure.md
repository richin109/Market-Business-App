# Capability 11: Deployment & Infrastructure

- [ ] **Capability complete** (all features below checked)

**Decision:** Development runs on this laptop now. Production later runs on a self-hosted **Proxmox VM**, not Kubernetes — simpler operationally and appropriately scaled for this application's load. The blueprint's original Kubernetes/Helm production design (§11.2) is not used; it's noted below only for context in case scale later justifies revisiting it.

## Feature 11.1 — Local Development (this laptop)
- [ ] Feature complete
- [x] `docker-compose.yml` with services: `web` (FastAPI + Jinja2/HTMX app, hot reload), `postgres` (15-alpine, persistent volume), `redis` (7-alpine, Celery broker/result backend), `celery-worker`, `celery-beat`. No separate `react-frontend`/Node service — the web UI is served by the same FastAPI app.
  - Evidence 2026-09-30 (Docker Desktop 29.8.1, Compose v5.5.1): `docker compose config --quiet` OK; `docker compose up --build -d` started all five services, postgres/redis healthy; `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`; Celery worker connected to Redis and beat started; in-container `pytest` 24 passed, `ruff check src tests` passed, `mypy src tests` passed. Dockerfile now points Ruff/mypy/pytest caches to `/tmp` because the non-root `mbs` user cannot write `/app`.
- [ ] `.env.example` documents Receipt MVP required variables (`DATABASE_URL`, `REDIS_URL`, persistent receipt-file store path, local Tesseract executable/language configuration, JWT secret); Google, Square, and Meta credentials are optional future-capability placeholders only.
- [ ] Generate and commit a version-pinned Tailwind CSS static asset with the standalone CLI; serve it locally from the web/reverse-proxy layer in production. The production content-security policy must not require Tailwind CDN access.
- [x] 🧑‍💻 Install the WSL 2 Linux distribution **Ubuntu 26.04 LTS** on this laptop and make it the default: in an Administrator PowerShell run `wsl --update`, `wsl --install -d Ubuntu-26.04`, create the Linux username/password, then `wsl --set-default Ubuntu-26.04`. Ubuntu LTS matches the recommended production VM OS family and Docker Desktop's default WSL integration. Validation: `wsl -l -v` lists `Ubuntu-26.04` as the default (`*`) with VERSION `2`, and `wsl --version` reports WSL 2.1.5 or later. See [the Windows Docker guide](../../user-docs/Docker_Windows11_Installation_Guide.md).
  - Evidence 2026-09-30: `wsl -l -v` → `* Ubuntu-26.04  Stopped  2`; `wsl --version` → WSL 3.0.1.0, kernel 6.18.40.1-1, Windows 10.0.26200.9550.
- [x] 🧑‍💻 Install Docker Desktop (or Docker Engine + Compose) on this laptop if not already installed: https://docs.docker.com/get-docker/
  - Evidence 2026-09-30: Docker Desktop per-user install (WSL 2 backend, Windows containers disabled); `docker info` → `Docker Desktop (containerized) / linux / server 29.8.1`; `docker compose version` → v5.5.1; `docker run --rm hello-world` succeeded.
- [ ] `make`/script targets (or a simple `run.sh`) for `up`, `down`, `logs`, `migrate`, `test` to keep local workflow one-command simple.
- [ ] The local `migrate` target applies version-controlled Alembic revisions; schema changes made during development are captured in a new revision rather than left as manual database edits. The test target applies migrations when preparing its database.

## Feature 11.2 — Production Target: Proxmox VM
- [ ] Feature complete
- [ ] 🧑‍💻 Provision a Linux VM (Debian or Ubuntu Server LTS recommended) inside Proxmox with enough disk for Postgres data + receipt image storage; Proxmox docs: https://pve.proxmox.com/pve-docs/
- [ ] 🧑‍💻 Assign the VM a static IP (or DHCP reservation) on your network and decide whether it's reachable only on your LAN or exposed externally (affects the reverse-proxy/TLS step below).
- [ ] Install Docker Engine + Docker Compose plugin on the VM. Use an explicitly separate immutable production Compose profile/override with pinned image digests, no bind-mounted source, no hot reload or debug, production-only secrets, health checks/restart policies, and restricted published ports; do not run the development `docker-compose.yml` unchanged with only different environment values.
- [ ] Add a reverse proxy (Caddy recommended for automatic HTTPS with minimal config, or Nginx if you already run Nginx elsewhere): Caddy docs https://caddyserver.com/docs/ — terminates TLS and proxies to the FastAPI `web` service. Even on a LAN, authenticated browser use requires HTTPS with a trusted certificate so `Secure` session cookies are sent; do not use plain HTTP LAN access as a production workaround.
- [ ] 🧑‍💻 If exposing outside the LAN, either configure port-forwarding + a DNS record you control, or use a tunnel service (e.g., Cloudflare Tunnel) instead of opening inbound ports directly: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- [ ] Production recovery targets are RPO <= 24 hours and RTO <= 8 hours. Schedule encrypted database and receipt-file backups at least nightly, and run a timed restore test proving both targets; receipt images are business data and are not covered by a database-only backup.
- [ ] Document the encrypted backup destination, retention, encryption-key owner and recovery procedure, and restore-test owner before storing real receipts. Complete the applicable real-data approvals in [the implementation-readiness gate](../02-implementation-readiness.md).
- [ ] Secrets (DB credentials, JWT secret, and future Google/Square/Meta WhatsApp credentials if enabled) stored in an `.env` file with restricted file permissions on the VM, or a secrets manager if one is already in use; never committed to source control.

## Feature 11.3 — CI/CD Pipeline
- [ ] Feature complete
- [ ] GitHub Actions: lint (`ruff`, `mypy`) and fast source tests → build a versioned, digest-pinned candidate image → run the MVP-specific profile from that image against migrated production-like test services → deploy only the same passing digest after its release gate passes. MVP 7 includes all 110 implemented source regression equivalents; MVP 8 runs the full MBS suite. Record digest, migrations, test/browser versions, and profile results together.
- [ ] Deploy stage: back up database and file store, pull the versioned image, run exactly one Alembic migration job, deploy web/worker services only after migration success, then run health and workflow smoke tests. Do not run migrations independently in every web/worker startup.
- [ ] Define rollback by migration compatibility: roll application images back only when the schema remains compatible; otherwise restore database and file backups under the RPO/RTO procedure. Document failed-migration and failed-smoke-test recovery.
- [ ] 🧑‍💻 Add repository secrets in GitHub for deploy SSH key/host and any registry credentials: repo Settings → Secrets and variables → Actions.

## Feature 11.4 — Future Scaling Option (not built now)
- [ ] Feature complete (or explicitly marked "not pursuing")
- [ ] If usage grows beyond a single VM (multiple concurrent users, heavier OCR/import volume), revisit Kubernetes (Helm charts) as in the original blueprint §11.2 — deferred until there's a concrete need.

## Feature 11.5 — Receipt MVP Early Deployment

- [ ] Feature complete
- [ ] Deploy the receipt-only vertical slice with Docker Compose: web app, Postgres, Redis/Celery worker with Tesseract + OpenCV installed, and persistent protected receipt-file storage. Do not require Google, Square, WhatsApp, or downstream MBS services to be configured.
- [ ] Provide a one-time secure first-ADMIN bootstrap command after migrations; require the operator to enter credentials locally, create no default password, and document an audited recovery/reset path. Provide authenticated manager upload/review UI, health check, and smoke test proving saved OCR data and receipt rows survive an app/container restart without another OCR call.
- [ ] For initial use, restrict access to the laptop or trusted LAN. A local loopback-only development session is not a LAN release; authenticated LAN access requires HTTPS with a trusted certificate, secure authentication, and firewall/reverse-proxy configuration before real receipts or other business data are used.
- [ ] Complete automated Postgres and receipt-file backup plus a tested restore before storing real receipts; keep uploads outside ephemeral container filesystems.
- [ ] Promote the same versioned Docker images/configuration from this internal MVP to the Proxmox target when it is ready; add later capabilities in subsequent releases.
