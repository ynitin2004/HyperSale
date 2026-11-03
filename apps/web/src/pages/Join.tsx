import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Api, ApiError } from '../api/client'
import { signIn, signOut, useSession } from '../auth'
import { navigate } from '../router'

// D45: an invite link. Works signed out; a new invitee chooses a password, an existing one signs in.
export function JoinPage({ token }: { token: string }) {
  const session = useSession()
  const qc = useQueryClient()
  const invite = useQuery({ queryKey: ['invite', token], queryFn: () => Api.lookupInvite(token), retry: false })
  const [mode, setMode] = useState<'new' | 'existing'>('new')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (invite.error) return <Shell><p className="error">{invite.error instanceof ApiError ? invite.error.message : 'This invite link is not valid.'}</p></Shell>
  if (!invite.data) return <Shell><p className="muted">Checking your invite…</p></Shell>
  const { email, role, workspace_name: workspace, state } = invite.data
  if (state !== 'pending') return <Shell><p className="error" data-testid="invite-state">This invite has been {state}. Ask for a new link.</p></Shell>

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      await qc.invalidateQueries({ queryKey: ['me'] })
      navigate('/')
    } catch (e) {
      if (e instanceof ApiError && e.code === 'account_exists') {
        setMode('existing')
        setError(`${email} already has an account. Sign in with its password to join.`)
      } else setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const signedInAs = session?.email
  return (
    <Shell>
      <h1 data-testid="join-title">Join {workspace} as {role}</h1>
      <p className="muted">This invite is for <strong>{email}</strong>.</p>
      {session ? (
        <div className="card form">
          <p className="small">Signed in as {signedInAs ?? 'someone'}.</p>
          <button disabled={busy} onClick={() => run(() => Api.acceptInvite({ token }).then(() => undefined))}>Join {workspace}</button>
          <button className="link" onClick={() => signOut()}>Use a different account</button>
        </div>
      ) : (
        <form className="card form" data-testid="join-form" onSubmit={(e) => {
          e.preventDefault()
          if (mode === 'new') {
            if (password !== confirm) return setError('The passwords do not match.')
            run(async () => {
              await Api.acceptInvite({ token, password })
              await signIn(email, password)
            })
          } else {
            run(async () => {
              await signIn(email, password)
              await Api.acceptInvite({ token })
            })
          }
        }}>
          <label>{mode === 'new' ? 'Choose a password' : 'Password'}
            <input type="password" minLength={8} value={password} required autoComplete={mode === 'new' ? 'new-password' : 'current-password'}
              onChange={(e) => setPassword(e.target.value)} data-testid="join-password" />
          </label>
          {mode === 'new' && (
            <label>Confirm password
              <input type="password" minLength={8} value={confirm} required autoComplete="new-password" onChange={(e) => setConfirm(e.target.value)} />
            </label>
          )}
          <button type="submit" disabled={busy}>{busy ? 'Joining…' : mode === 'new' ? 'Create account and join' : 'Sign in and join'}</button>
          <button type="button" className="link" onClick={() => (setMode(mode === 'new' ? 'existing' : 'new'), setError(null))}>
            {mode === 'new' ? 'I already have an account' : 'I need a new account'}
          </button>
        </form>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="login">
      <p className="eyebrow">HYPERSALE</p>
      {children}
    </main>
  )
}
