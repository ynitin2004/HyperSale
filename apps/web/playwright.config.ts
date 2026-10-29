// E2E against stubbed voice + scoring providers (RULES §4, D31): no live API cost.
// The suite starts the API, the worker and a preview of the built SPA itself. Run
// `python scripts/e2e_setup.py` against E2E_DATABASE_URL first (CI does).
import { defineConfig } from '@playwright/test'

const DB = process.env.E2E_DATABASE_URL ?? 'postgresql+asyncpg://postgres:postgres@localhost:5432/hypersale_e2e'
const PY = process.env.E2E_PYTHON ?? 'python'
export const JWT_SECRET = process.env.E2E_JWT_SECRET ?? 'e2e-secret-that-is-at-least-32-bytes-long'
const API_PORT = 8765
const WEB_PORT = 4173
const WORKER_HEALTH_PORT = 8766

const backendEnv = {
  DATABASE_URL: DB,
  WORKER_DATABASE_URL: DB,
  SUPABASE_JWT_SECRET: JWT_SECRET,
  SUPABASE_JWKS_URL: '',
  VOICE_PROVIDER: 'stub',
  SCORING_PROVIDER: 'stub',
  STUB_VOICE_TURN_GAP_SECONDS: '0.25',
  RECORDING_STORE: 'local',
  RECORDING_DIR: '../../var/e2e-recordings',
  CORS_ORIGINS: `http://127.0.0.1:${WEB_PORT}`,
  WORKER_POLL_SECONDS: '0.2',
  APP_ENV: 'e2e',
}

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: `${PY} -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '../../services/backend',
      url: `http://127.0.0.1:${API_PORT}/health`,
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `${PY} -m app.workers.main`,
      cwd: '../../services/backend',
      env: { ...backendEnv, WORKER_HEALTH_PORT: String(WORKER_HEALTH_PORT) },
      url: `http://127.0.0.1:${WORKER_HEALTH_PORT}/`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite build --mode e2e && npx vite preview --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { VITE_API_BASE_URL: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
