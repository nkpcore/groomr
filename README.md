# CHAIR — Hyperlocal Men's Grooming Marketplace & Salon SaaS

CHAIR connects men in India with verified local barbershops and gives salon partners **CHAIR Business**—a real-time operations console for chairs, shifts, walk-ins, appointments, and earnings.

> **Current Repository Stage:** **Phase 0 (Foundation) Complete** — ready for local database startup and **Phase 1 (Auth, RBAC & Consents)**.

---

## Repository Structure

- [AGENTS.md](AGENTS.md) — Engineering & AI agent constitution
- [.agents/rules/](.agents/rules/) — Native Antigravity scoped rules (core governance, FastAPI/PostGIS, booking invariants, CHAIR UI system, Indian privacy/trust)
- [PRODUCT.md](PRODUCT.md) — Confirmed product scope and principles
- [docs/adr/0001-architecture-and-stack.md](docs/adr/0001-architecture-and-stack.md) — Architecture Decision Record
- [docs/architecture/database-schema.md](docs/architecture/database-schema.md) — 33+ core entity PostgreSQL/PostGIS schema & booking state machine
- [docs/plans/roadmap.md](docs/plans/roadmap.md) & [docs/plans/phase-0-foundation-plan.md](docs/plans/phase-0-foundation-plan.md) — Phased implementation plan
- [docs/compliance-checklist.md](docs/compliance-checklist.md) — Missing secrets register & Indian CA/legal review checklist
- [docs/mobile-packaging.md](docs/mobile-packaging.md) — Android SDK / Expo EAS packaging guide
- [.env.example](.env.example) & [docker-compose.yml](docker-compose.yml) — Local configuration & PostgreSQL/PostGIS + Redis containers

Application workspaces:
- `apps/api/` — Python FastAPI + SQLAlchemy 2.0 + GeoAlchemy2 + Alembic + Celery + Pytest
- `apps/mobile/` — React Native + Expo Router + TypeScript (Customer App + RN Web)
- `apps/web/` — Next.js + TypeScript + Tailwind CSS (Partner PWA & Admin Console)
- `packages/shared-types/` — Shared TypeScript types, paise currency utilities, and EN/HI i18n keys

---

## Host Environment Status (Verified)

| Tool | Status on Host | Notes |
| --- | --- | --- |
| `git` | Installed (`2.55.0`) | Initialized on branch `main` |
| `node` / `npm` | Installed (`v24.19.0` / `12.2.1`) | Manages npm workspaces (`apps/mobile`, `apps/web`, `packages/shared-types`) |
| `python` / `uv` | Installed (`3.14.7` / `0.12.22`) | Manages `apps/api` FastAPI, Alembic, Celery, Pytest |
| `java` & Android SDK | Installed (`JDK 17`, `%LOCALAPPDATA%\Android\Sdk`) | Set `ANDROID_HOME` & add `platform-tools` to `PATH` before running Android emulator builds |
| Docker / PostgreSQL / Redis | **Not installed locally** | Install Docker Desktop (`docker compose up -d`) or supply cloud PostgreSQL+PostGIS & Redis URLs in `.env` |

---

## Quick Verification & Local Run Commands

```powershell
# 1. Copy environment template (never commit .env)
Copy-Item .env.example .env

# 2. Start PostgreSQL + PostGIS & Redis (once Docker Desktop is installed)
docker compose up -d

# 3. Run migrations & [DEMO] seed (requires live PostgreSQL + PostGIS)
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run python -m chair_api.db.seeds.demo_seed

# 4. Run backend lint, typecheck, and tests
uv --directory apps/api run ruff check src tests
uv --directory apps/api run mypy src
uv --directory apps/api run pytest -v

# 5. Run frontend & shared package checks
npm run typecheck
npm run lint
npm run test
```
