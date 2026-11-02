#!/usr/bin/env bash
# Temporary public URL for testers (WALKTHROUGH §13): API + worker on the real .env, the built web
# app with an /api proxy, and a Cloudflare quick tunnel. Stops when this script stops; the URL
# changes on every start. Logs land in var/tunnel/.
set -euo pipefail
cd "$(dirname "$0")/.."
LOG=var/tunnel
mkdir -p "$LOG"
PY=services/backend/.venv/Scripts/python.exe
export PYTHONPATH="services/backend${PYTHONPATH:+;$PYTHONPATH}"
SB_URL=$($PY -c "from dotenv import dotenv_values;print(dotenv_values('.env')['SUPABASE_URL'])")
SB_KEY=$($PY -c "from dotenv import dotenv_values;print(dotenv_values('.env')['SUPABASE_PUBLISHABLE_KEY'])")

trap 'kill $(jobs -p) 2>/dev/null' EXIT
$PY -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > "$LOG/api.log" 2>&1 &
$PY -m app.workers.main > "$LOG/worker.log" 2>&1 &
(cd apps/web && VITE_API_BASE_URL=. VITE_SUPABASE_URL="$SB_URL" VITE_SUPABASE_PUBLISHABLE_KEY="$SB_KEY" \
  npx vite build > "../../$LOG/build.log" 2>&1 && npx vite preview --host 127.0.0.1 --port 4174 --strictPort \
  > "../../$LOG/web.log" 2>&1) &
"/c/Program Files (x86)/cloudflared/cloudflared.exe" tunnel --no-autoupdate --url http://127.0.0.1:4174 > "$LOG/cloudflared.log" 2>&1 &
wait
