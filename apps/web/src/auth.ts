// Supabase Auth over its REST API (D7). The SPA holds only the user's own session; the
// publishable key identifies the project and grants nothing on its own.
import { useSyncExternalStore } from 'react'

export type AuthSession = {
  access_token: string
  refresh_token: string
  expires_at: number // epoch seconds
  email: string | null
}

const STORAGE_KEY = 'hs.session'
const SB_URL = (import.meta.env.VITE_SUPABASE_URL ?? '').replace(/\/$/, '')
const SB_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? ''

let current: AuthSession | null = load()
const listeners = new Set<() => void>()

function load(): AuthSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuthSession) : null
  } catch {
    return null
  }
}

function save(session: AuthSession | null) {
  current = session
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private mode: the session still lives in memory */
  }
  listeners.forEach((fn) => fn())
}

async function tokenRequest(grant: 'password' | 'refresh_token', body: object): Promise<AuthSession> {
  if (!SB_URL || !SB_KEY) throw new Error('Auth is not configured (VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY)')
  const res = await fetch(`${SB_URL}/auth/v1/token?grant_type=${grant}`, {
    method: 'POST',
    headers: { apikey: SB_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error_description ?? data.msg ?? data.message ?? `Sign-in failed (${res.status})`)
  return {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_at: data.expires_at ?? Math.floor(Date.now() / 1000) + (data.expires_in ?? 3600),
    email: data.user?.email ?? null,
  }
}

export async function signIn(email: string, password: string) {
  save(await tokenRequest('password', { email, password }))
}

export function signOut() {
  save(null)
}

let refreshing: Promise<void> | null = null

export async function getAccessToken(): Promise<string | null> {
  if (!current) return null
  if (current.expires_at - 60 > Date.now() / 1000) return current.access_token
  refreshing ??= tokenRequest('refresh_token', { refresh_token: current.refresh_token })
    .then(save)
    .catch(() => save(null))
    .finally(() => (refreshing = null))
  await refreshing
  return current?.access_token ?? null
}

export function useSession(): AuthSession | null {
  return useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => current,
  )
}
