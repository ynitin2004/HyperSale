#!/bin/sh
# One image, three roles. Fly.io runs `api` and `worker` as separate processes from this
# same build, and `migrate` as a release command, so they can never drift apart.
set -eu

ROLE="${PROCESS_ROLE:-api}"

case "$ROLE" in
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  worker)
    exec python -m app.workers.main
    ;;
  migrate)
    # The catalog seed is idempotent and versioned (D30), so every release re-runs it.
    alembic upgrade head
    exec python -m app.modules.catalog.seed
    ;;
  *)
    echo "Unknown PROCESS_ROLE '$ROLE' (expected: api, worker, migrate)" >&2
    exit 64
    ;;
esac
