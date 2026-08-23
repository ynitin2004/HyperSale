# HyperSale

AI sales-performance platform: live voice practice and evidence-backed coaching.

`MASTER_PRODUCT.md` is the product source of truth. Read it before changing product behavior and update its living-memory section at the end of a work session.

## Local development

Prerequisites: Node 20+, pnpm 9+, Python 3.12+, Docker Desktop, and a Supabase project for the full stack.

```bash
cp .env.example .env
pnpm install
pnpm dev:web

docker compose up -d db

cd services/backend
python -m venv .venv
.venv/Scripts/pip install -e '.[dev]'
.venv/Scripts/alembic upgrade head
.venv/Scripts/uvicorn app.main:app --reload      # API
.venv/Scripts/python -m app.workers.main         # worker, in a second terminal
```

The web app uses `http://localhost:5173`. `GET /health` is liveness; `GET /api/v1/ready` also checks the database.

## Architecture notes that are easy to get wrong

**Tenancy has two boundaries.** Every workspace query goes through `tenant_session(workspace_id)`, which sets transaction-local GUCs that the RLS policies read. Route handlers must take the `TenantSession` dependency rather than opening a session themselves. Row-level security is the backstop, not the primary control.

**RLS needs the right database roles.** Postgres exempts superusers and (without `FORCE`) table owners from RLS, so the application must connect as an unprivileged role or the second boundary is silently off. The worker's queue dispatcher is the one cross-tenant component and needs a role with `BYPASSRLS`; everything else must not have it.

**One image, three roles.** `services/backend` builds a single image whose `PROCESS_ROLE` selects `api`, `worker`, or `migrate`. Fly.io runs the first two as processes and the third as a release command.

**Costs are configuration.** Rate settings default to zero, and a zero rate applied to real audio is recorded as `rate_missing` so an unmeasured cost never reads as a free one.

## Generated API client

Frontend request types are generated, never hand-written:

```bash
cd services/backend && .venv/Scripts/python -m app.openapi > openapi.json
cd packages/api-client && pnpm generate
```

## Tests

```bash
cd services/backend
.venv/Scripts/python -m pytest             # unit tests; integration tests skip
```

Integration tests prove tenant isolation and queue semantics and therefore need a real Postgres:

```bash
docker compose up -d db
cd services/backend
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/hypersale .venv/Scripts/alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/hypersale .venv/Scripts/python -m pytest
```

They create an unprivileged `hypersale_app_test` role so RLS is actually exercised. CI always sets `TEST_DATABASE_URL`, so these never skip there.

## M0 gates

Configuration is in place; the remaining M0 gates need real credentials and a real session:

- Point `SUPABASE_JWKS_URL` (or `SUPABASE_JWT_SECRET`) at a Supabase project and run migrations against it.
- Run a three-minute voice session, then set the measured `REALTIME_AUDIO_*` rates from the provider's billing.
- Test local plus remote audio capture on Chrome and Safari; record the mic-only fallback if remote-track capture fails.
