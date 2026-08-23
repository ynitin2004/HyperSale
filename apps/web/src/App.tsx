import { useState } from 'react'

type Health = { status: string; request_id: string }

export function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function checkApi() {
    setError(null)
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
      const response = await fetch(`${baseUrl}/health`)
      if (!response.ok) throw new Error(`API returned ${response.status}`)
      setHealth((await response.json()) as Health)
    } catch (cause) {
      setHealth(null)
      setError(cause instanceof Error ? cause.message : 'Unable to reach the API')
    }
  }

  return <main>
    <section className="hero">
      <p className="eyebrow">HYPERSALE · M0</p>
      <h1>Practice the call.<br /><em>Prove the coaching.</em></h1>
      <p className="summary">The M0 shell is live. Voice, cost metering, and browser-audio capture are the next validation gates.</p>
      <button onClick={checkApi}>Check API health</button>
      {health && <p className="success">API {health.status} · request {health.request_id}</p>}
      {error && <p className="error">{error}</p>}
    </section>
    <section className="principles" aria-label="Product principles">
      <article><strong>Evidence first</strong><span>Every score will point to real, attributed transcript evidence.</span></article>
      <article><strong>Fast loop</strong><span>Metrics first, full coaching under thirty seconds.</span></article>
      <article><strong>Measured trust</strong><span>Model scoring will be compared with external sales-manager labels.</span></article>
    </section>
  </main>
}

