# Docker and Docker Compose Installation Guide for Windows 11

This guide installs **Docker Desktop** (Docker Engine, CLI, and Compose) on a Windows 11 development laptop using WSL 2. It supports the [MBS implementation plan](../plan/00-overview.md): local Docker Compose runs the FastAPI web app, PostgreSQL, Redis, and Celery. This is not the production Proxmox VM setup. Use only synthetic data and mocked providers until the [implementation-readiness gate](../plan/02-implementation-readiness.md) permits real data.

---

## 📋 System Requirements
Before starting, check the current [Docker Desktop Windows system requirements](https://docs.docker.com/desktop/setup/install/windows-install/#system-requirements) for your Windows 11 release and processor architecture:
* **OS:** A supported, up-to-date Windows 11 release; use Linux containers for this project (including on Home and Education).
* **Processor:** A supported 64-bit x86-64 or Arm64 processor; select the matching installer.
* **RAM:** 8 GB system RAM minimum for the WSL 2 backend.
* **WSL:** Version 2.1.5 or later, with WSL 2 enabled.
* **Firmware:** Hardware virtualization enabled in BIOS/UEFI.

---

## 🛠️ Step 1: Enable WSL 2 (Windows Subsystem for Linux)
Docker Desktop uses the WSL 2 backend for this local Linux-container setup.

1. Open **PowerShell** or **Windows Terminal** as an **Administrator** (Right-click -> Run as Administrator).
2. Check whether WSL is already installed:
   ```powershell
   wsl --version
   ```
   If WSL is missing, install it:
   ```powershell
   wsl --install
   ```
   If WSL is installed but older than 2.1.5 (or `wsl --version` does not show version details), update it:
   ```powershell
   wsl --update
   ```
3. **Restart your computer** if prompted, then run `wsl --version` again to verify the version.
4. Install **Ubuntu 26.04 LTS**, the recommended Linux distribution for this application (an LTS release in the same family as the recommended production VM OS):
   ```powershell
   wsl --install -d Ubuntu-26.04
   ```
   When the Ubuntu console opens, create your Linux username and password. If `Ubuntu-26.04` is not listed, run `wsl --list --online` and choose the newest `Ubuntu-XX.04` LTS entry.
5. Make it the default distribution and verify it runs on WSL 2:
   ```powershell
   wsl --set-default Ubuntu-26.04
   wsl -l -v
   ```
   Expected: `Ubuntu-26.04` is marked with `*` and shows VERSION `2`. If it shows `1`, run `wsl --set-version Ubuntu-26.04 2`. (After Docker Desktop is installed, its internal `docker-desktop` distribution will also appear; do not use it for development.)

---

## 📥 Step 2: Download and Install Docker Desktop
Docker Desktop for Windows includes **Docker Engine**, **Docker CLI client**, and **Docker Compose**.

1. Download the installer for your processor (x86-64 or Arm64) from the [official Docker Desktop Windows page](https://docs.docker.com/desktop/setup/install/windows-install/). Check its Arm availability and requirements there if using Windows on Arm.
2. Run the downloaded `Docker Desktop Installer.exe`.
3. When prompted for a backend, select **Use WSL 2 instead of Hyper-V**. On systems with only one supported backend, the installer may select it automatically.
4. Follow the remaining on-screen prompts and click **Close** once the setup finishes.

---

## 🚀 Step 3: Initial Configuration
1. Launch **Docker Desktop** from your Windows Start Menu.
2. Accept the **Docker Subscription Service Agreement** when prompted.
3. Wait until Docker Desktop reports that its engine is running; keep **Linux containers** selected for this project.
4. If using Docker commands inside a WSL distribution other than the default one, enable that distribution under **Settings > Resources > WSL Integration**, then select **Apply**. Docker Desktop normally integrates the default WSL 2 distribution automatically. Windows PowerShell does not need distribution integration.

---

## 🧪 Step 4: Verify the Installation
Open **PowerShell** or **Command Prompt** (or an integrated **WSL 2 Linux terminal**) and run the following checks:

### 1. Check Docker Version
```bash
docker --version
```

### 2. Check Docker Compose Version
```bash
docker compose version
```

### 3. Run a Test Container
Verify that Docker can fetch and run images correctly:
```bash
docker run hello-world
```

The first run downloads a public test image. A successful greeting confirms Docker can reach the Linux-container engine; `docker --version` and `docker compose version` alone only check the installed clients.

## Next: MBS Local Development

From **PowerShell** in the repository root, verify the planned local web, Postgres, Redis, and Celery stack:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose config
docker compose up --build -d postgres redis
docker compose run --rm --build migrate
docker compose up --build -d web celery-worker celery-beat
docker compose run --rm --build test
docker compose run --rm --build test-migrations-postgres
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health
docker compose down
```

The health endpoint should return `{"status":"ok"}`. PostgreSQL is the sole runtime and database-test engine. The app uses the latest published official Python 3.14 Trixie image (currently 3.14.7); Python 3.12 remains the compatibility minimum. Tests are excluded from runtime; the dedicated test target includes PostgreSQL 18 clients and Chromium. Rebuild after source/test/migration changes, then use `docker compose run --rm test pytest <test-file> -q` for a focused run. Missing database configuration fails instead of silently skipping. No Node installation is required.

Compose assembles connection credentials from `POSTGRES_*` unless `DATABASE_URL` overrides them; split fields handle literal special characters. Published PostgreSQL dev ports bind only to loopback (defaults 5432 for the app and 55432 for the dedicated synthetic test service). Configure `MBS_POSTGRES_PORT`/`MBS_TEST_POSTGRES_PORT` if those ports are occupied. A Windows host process must use `127.0.0.1`, not the container hostname `postgres`, and must not use application credentials for tests. See [README](../README.md#local-development) for host-debugging caveats and the shared generic SQLAlchemy configuration.

The original stack commands were verified 2026-10-01 (Docker Engine 29.8.1, Compose v5.5.1, PostgreSQL 18.6, Redis 8.10.2). D-77 conversion evidence is recorded in [the current slice](../plan/03-current-slice.md); this guide alone is not test evidence. The earlier data-volume reset was explicitly authorized; never use `docker compose down -v` as routine troubleshooting. Open a new terminal if it predates Docker installation. Production must use its separately gated immutable profile without reload, host DB ports, test services, source mounts, or example passwords.
