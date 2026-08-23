# HyperSale

AI sales-performance platform: live voice practice and evidence-backed coaching.

`MASTER_PRODUCT.md` is the product source of truth. Read it before changing product behavior and update its living-memory section at the end of a work session.

## Local development

Prerequisites: Node 20+, pnpm 9+, Python 3.12+, Docker Desktop, and a Supabase project for the full stack.

```bash
cp .env.example .env
pnpm install
pnpm dev:web
cd services/backend && python -m venv .venv && .venv/Scripts/pip install -e '.[dev]'
cd services/backend && .venv/Scripts/uvicorn app.main:app --reload
```

The web app uses `http://localhost:5173`; API health is at `http://localhost:8000/health`.

## M0 gates

Before implementing product features, configure real provider credentials and complete the cost and browser audio-capture spikes described in `MASTER_PRODUCT.md`.

