// Thin typed client. Every shape comes from the generated `schema.d.ts` (RULES §1: no
// hand-written API types); regenerate with `pnpm gen:api` after an API change.
import { getAccessToken, signOut } from '../auth'
import type { components } from './schema'

type S = components['schemas']
export type Scenario = S['ScenarioOut']
export type PracticeSession = S['SessionOut']
export type ConnectResult = S['ConnectOut']
export type EndResult = S['EndOut']
export type Turn = S['TurnOut']
export type Report = S['ReportOut']
export type Criterion = S['ScoredCriterionOut']
export type Evidence = S['EvidenceOut']
export type Stage = S['StageOut']
export type Integrity = S['IntegrityOut']

export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getAccessToken()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && typeof init.body === 'string') headers.set('Content-Type', 'application/json')
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (res.status === 401) signOut()
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const err = body.error ?? {}
    throw new ApiError(res.status, err.code ?? `http_${res.status}`, err.message ?? res.statusText, err.request_id)
  }
  if (res.status === 204) return undefined as T
  const type = res.headers.get('content-type') ?? ''
  return (type.includes('json') ? res.json() : res.blob()) as Promise<T>
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const Api = {
  config: () => request<{ voice_provider: string; scoring_provider: string; environment: string }>('/api/v1/config'),
  me: () => request<S['MeResponse']>('/api/v1/me'),
  scenarios: () => request<Scenario[]>('/api/v1/catalog/scenarios'),
  sessions: () => request<PracticeSession[]>('/api/v1/practice/sessions'),
  session: (id: string) => request<PracticeSession>(`/api/v1/practice/sessions/${id}`),
  createSession: (scenarioId: string) => post<PracticeSession>('/api/v1/practice/sessions', { scenario_id: scenarioId }),
  connect: (id: string, sdpOffer: string | null) =>
    post<ConnectResult>(`/api/v1/practice/sessions/${id}/connect`, { sdp_offer: sdpOffer }),
  end: (id: string, body: S['EndIn']) => post<EndResult>(`/api/v1/practice/sessions/${id}/end`, body),
  transcript: (id: string) => request<Turn[]>(`/api/v1/practice/sessions/${id}/transcript`),
  uploadChunk: (id: string, seq: number, blob: Blob) =>
    request<void>(`/api/v1/practice/sessions/${id}/recording/${seq}`, {
      method: 'PUT',
      body: blob,
      headers: { 'Content-Type': blob.type || 'audio/webm' },
    }),
  recording: (id: string) => request<Blob>(`/api/v1/practice/sessions/${id}/recording`),
  report: (id: string) => request<Report>(`/api/v1/reports/${id}`),
  latency: () => request<Stage[]>('/api/v1/metrics/latency'),
  integrity: () => request<Integrity>('/api/v1/evidence/integrity'),
}
