import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Api } from './api/client'
import { signIn, signOut, useSession } from './auth'
import { HomePage } from './pages/Home'
import { LatencyPage } from './pages/Latency'
import { PracticePage } from './pages/Practice'
import { RateItemPage, RateListPage } from './pages/Rate'
import { ReportPage } from './pages/Report'
import { TeamPage } from './pages/Team'
import { navigate, useRoute } from './router'

export function App() {
  const session = useSession()
  const route = useRoute()
  const me = useQuery({ queryKey: ['me'], queryFn: Api.me, retry: false, enabled: !!session })
  if (!session) return <LoginPage />
  const manager = me.data?.role === 'manager' || me.data?.role === 'owner'
  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="#/">HYPERSALE</a>
        <nav>
          <a href="#/" className={route.name === 'home' ? 'active' : ''}>Practice</a>
          {manager && <a href="#/team" className={route.name === 'team' ? 'active' : ''}>Team</a>}
          <a href="#/rate" className={route.name.startsWith('rate') ? 'active' : ''}>Label</a>
          <a href="#/latency" className={route.name === 'latency' ? 'active' : ''}>Latency</a>
          <WhoAmI />
          <button className="link" onClick={() => (signOut(), navigate('/'))}>Sign out</button>
        </nav>
      </header>
      <main className="page">
        {route.name === 'home' && <HomePage />}
        {route.name === 'practice' && <PracticePage scenarioId={route.scenarioId} />}
        {route.name === 'report' && <ReportPage reportId={route.reportId} />}
        {route.name === 'latency' && <LatencyPage />}
        {route.name === 'team' && <TeamPage />}
        {route.name === 'rate' && <RateListPage />}
        {route.name === 'rateItem' && <RateItemPage itemId={route.itemId} />}
      </main>
    </div>
  )
}

function WhoAmI() {
  const me = useQuery({ queryKey: ['me'], queryFn: Api.me, retry: false })
  if (!me.data) return null
  return <span className="muted small" data-testid="whoami">{me.data.email ?? 'signed in'} · {me.data.role}</span>
}

function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <main className="login">
      <p className="eyebrow">HYPERSALE</p>
      <h1>Practice the call.<br /><em>Prove the coaching.</em></h1>
      <form
        className="card form"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError(null)
          try {
            await signIn(email, password)
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Sign-in failed')
          } finally {
            setBusy(false)
          }
        }}
      >
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" /></label>
        <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
    </main>
  )
}
