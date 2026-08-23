import { useState } from 'react'

type Config = {
  environment: string
  auth_configured: boolean
  realtime_configured: boolean
  request_id: string
}

type Check = { label: string; ready: boolean; detail: string }

const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`)
  if (!response.ok) throw new Error(`${path} returned ${response.status}`)
  return (await response.json()) as T
}

export function App() {
  const [checks, setChecks] = useState<Check[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function runGateCheck() {
    setBusy(true)
    setError(null)
    try {
      const [health, config] = await Promise.all([
        getJson<{ status: string }>('/health'),
        getJson<Config>('/api/v1/config'),
      ])
      // Readiness touches the database, so it is allowed to fail without failing the page.
      const database = await getJson<{ database: boolean }>('/api/v1/ready').catch(() => ({
        database: false,
      }))
      setChecks([
        { label: 'API', ready: health.status === 'ok', detail: config.environment },
        {
          label: 'Database',
          ready: database.database,
          detail: database.database ? 'migrations applied' : 'unreachable or not migrated',
        },
        {
          label: 'Auth',
          ready: config.auth_configured,
          detail: config.auth_configured ? 'Supabase keys set' : 'set SUPABASE_JWKS_URL',
        },
        {
          label: 'Voice provider',
          ready: config.realtime_configured,
          detail: config.realtime_configured ? 'credentials set' : 'set OPENAI_API_KEY',
        },
      ])
    } catch (cause) {
      setChecks(null)
      setError(cause instanceof Error ? cause.message : 'Unable to reach the API')
    } finally {
      setBusy(false)
    }
  }

  return <main>
    <section className="hero">
      <p className="eyebrow">HYPERSALE · M0</p>
      <h1>Practice the call.<br /><em>Prove the coaching.</em></h1>
      <p className="summary">The M0 shell is live. Voice, cost metering, and browser-audio capture are the next validation gates.</p>
      <button onClick={runGateCheck} disabled={busy}>{busy ? 'Checking…' : 'Check M0 gates'}</button>
      {checks && <ul className="checks">
        {checks.map((check) => <li key={check.label} className={check.ready ? 'success' : 'pending'}>
          <strong>{check.ready ? '✓' : '○'} {check.label}</strong>
          <span>{check.detail}</span>
        </li>)}
      </ul>}
      {error && <p className="error">{error}</p>}
    </section>
    <section className="principles" aria-label="Product principles">
      <article><strong>Evidence first</strong><span>Every score will point to real, attributed transcript evidence.</span></article>
      <article><strong>Fast loop</strong><span>Metrics first, full coaching under thirty seconds.</span></article>
      <article><strong>Measured trust</strong><span>Model scoring will be compared with external sales-manager labels.</span></article>
    </section>
  </main>
}
