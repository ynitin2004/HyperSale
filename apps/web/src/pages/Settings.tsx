import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Api, ApiError, type Member, type WorkspaceSettings } from '../api/client'

// M4: retention, consent and spend (D46, D47), members and invites (D45), the audit log.
const usd = (micro: number) => `$${(micro / 1_000_000).toFixed(2)}`
const errorText = (e: unknown) => (e instanceof ApiError ? e.message : String(e))

export function SettingsPage() {
  const me = useQuery({ queryKey: ['me'], queryFn: Api.me, retry: false })
  const settings = useQuery({ queryKey: ['workspace-settings'], queryFn: Api.workspaceSettings })
  if (me.data && me.data.role === 'rep') return <p className="muted">Settings are for managers and owners.</p>
  if (settings.error) return <p className="error">Could not load settings: {errorText(settings.error)}</p>
  if (!settings.data || !me.data) return <p className="muted">Loading settings…</p>
  const owner = me.data.role === 'owner'
  return (
    <>
      <WorkspaceForm current={settings.data} />
      <Members owner={owner} self={me.data.user_id} />
      <Invites owner={owner} />
      <AuditLog />
    </>
  )
}

function WorkspaceForm({ current }: { current: WorkspaceSettings }) {
  const qc = useQueryClient()
  const [keep, setKeep] = useState(current.audio_retention_days === null)
  const [days, setDays] = useState(current.audio_retention_days ?? 90)
  const [unlimited, setUnlimited] = useState(current.monthly_limit_microusd === null)
  const [limit, setLimit] = useState((current.monthly_limit_microusd ?? 10_000_000) / 1_000_000)
  const [record, setRecord] = useState(current.record_roleplay_audio)
  const save = useMutation({
    mutationFn: () => Api.saveWorkspaceSettings({
      audio_retention_days: keep ? null : days,
      monthly_limit_microusd: unlimited ? null : Math.round(limit * 1_000_000),
      record_roleplay_audio: record,
    }),
    onSuccess: (data) => (qc.setQueryData(['workspace-settings'], data), qc.invalidateQueries({ queryKey: ['audit'] })),
  })
  const edit = current.can_edit
  const limitMicro = current.monthly_limit_microusd ?? null
  return (
    <section>
      <h2>Workspace</h2>
      <p className="muted" data-testid="month-spend">
        AI spend this month: <strong>{usd(current.month_spent_microusd)}</strong>
        {limitMicro !== null ? ` of ${usd(limitMicro)}` : ' (no limit)'}
        {limitMicro !== null && current.month_spent_microusd >= limitMicro && <span className="error"> · limit reached: new calls are blocked</span>}
      </p>
      {!edit && <p className="muted small">Only an owner can change these.</p>}
      <form className="card form" data-testid="settings-form" onSubmit={(e) => (e.preventDefault(), save.mutate())}>
        <fieldset disabled={!edit} style={{ border: 0, padding: 0, margin: 0, display: 'grid', gap: '.8rem' }}>
          <label>Delete call audio after (days)
            <input type="number" min={1} max={3650} value={days} disabled={keep} data-testid="retention-days"
              onChange={(e) => setDays(Number(e.target.value))} />
          </label>
          <label className="small"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} /> Keep audio forever</label>
          <p className="muted small">Transcripts and scores are kept either way, so reports and team trends still work.</p>
          <label>Monthly AI spend limit (USD)
            <input type="number" min={0} step={1} value={limit} disabled={unlimited} data-testid="spend-limit"
              onChange={(e) => setLimit(Number(e.target.value))} />
          </label>
          <label className="small"><input type="checkbox" checked={unlimited} onChange={(e) => setUnlimited(e.target.checked)} /> No limit</label>
          <p className="muted small">At the limit, new roleplays and uploads are refused. Calls already running finish.</p>
          <label className="small"><input type="checkbox" checked={record} data-testid="record-audio"
            onChange={(e) => setRecord(e.target.checked)} /> Record roleplay audio</label>
          {edit && <button type="submit" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>}
          {save.isSuccess && <p className="ok small" data-testid="settings-saved">Saved.</p>}
          {save.error && <p className="error" role="alert">{errorText(save.error)}</p>}
        </fieldset>
      </form>
    </section>
  )
}

function Members({ owner, self }: { owner: boolean; self: string }) {
  const qc = useQueryClient()
  const members = useQuery({ queryKey: ['members'], queryFn: Api.members })
  const [error, setError] = useState<string | null>(null)
  const act = async (fn: () => Promise<unknown>) => {
    setError(null)
    try {
      await fn()
      await Promise.all(['members', 'team', 'audit'].map((k) => qc.invalidateQueries({ queryKey: [k] })))
    } catch (e) {
      setError(errorText(e))
    }
  }
  const label = (m: Member) => m.email ?? `member ${m.user_id.slice(0, 8)}`
  return (
    <section>
      <h2>Members</h2>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="table" data-testid="members-table">
          <thead><tr><th>Member</th><th>Role</th><th>Joined</th><th /></tr></thead>
          <tbody>
            {(members.data ?? []).map((m) => (
              <tr key={m.user_id}>
                <td>{label(m)}{m.user_id === self && <span className="muted small"> (you)</span>}</td>
                <td>
                  {owner ? (
                    <select value={m.role} aria-label={`Role for ${label(m)}`}
                      onChange={(e) => act(() => Api.setRole(m.user_id, e.target.value as 'rep' | 'manager' | 'owner'))}>
                      <option value="rep">rep</option><option value="manager">manager</option><option value="owner">owner</option>
                    </select>
                  ) : m.role}
                </td>
                <td className="small">{new Date(m.created_at).toLocaleDateString()}</td>
                <td>{owner && m.user_id !== self && (
                  <button className="link" onClick={() => confirm(`Remove ${label(m)}? Their past calls stay.`) && act(() => Api.removeMember(m.user_id))}>
                    Remove</button>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Invites({ owner }: { owner: boolean }) {
  const qc = useQueryClient()
  const invites = useQuery({ queryKey: ['invites'], queryFn: Api.invites })
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'rep' | 'manager' | 'owner'>('rep')
  const [link, setLink] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  useEffect(() => setCopied(false), [link])
  const create = useMutation({
    mutationFn: () => Api.invite({ email, role }),
    onSuccess: (inv) => {
      setLink(`${window.location.origin}${window.location.pathname}#/join/${inv.token}`)
      setEmail('')
      qc.invalidateQueries({ queryKey: ['invites'] })
      qc.invalidateQueries({ queryKey: ['audit'] })
    },
  })
  const revoke = useMutation({
    mutationFn: (id: string) => Api.revokeInvite(id),
    onSuccess: () => (qc.invalidateQueries({ queryKey: ['invites'] }), qc.invalidateQueries({ queryKey: ['audit'] })),
  })
  return (
    <section>
      <h2>Invite someone</h2>
      <p className="muted">You get a link that works once, for that email, for 7 days. Send it however you like.</p>
      <form className="form inline" data-testid="invite-form" onSubmit={(e) => (e.preventDefault(), create.mutate())}>
        <input type="email" placeholder="name@company.com" value={email} required onChange={(e) => setEmail(e.target.value)} data-testid="invite-email" />
        <select value={role} onChange={(e) => setRole(e.target.value as typeof role)} aria-label="Role">
          <option value="rep">rep</option>
          {owner && <option value="manager">manager</option>}
          {owner && <option value="owner">owner</option>}
        </select>
        <button type="submit" disabled={create.isPending}>Create link</button>
      </form>
      {create.error && <p className="error" role="alert">{errorText(create.error)}</p>}
      {revoke.error && <p className="error" role="alert">{errorText(revoke.error)}</p>}
      {link && (
        <div className="card" data-testid="invite-link">
          <p className="small">Copy this now: it is shown only once.</p>
          <code style={{ wordBreak: 'break-all' }}>{link}</code>
          <p><button onClick={() => navigator.clipboard?.writeText(link).then(() => setCopied(true))}>{copied ? 'Copied' : 'Copy link'}</button></p>
        </div>
      )}
      {!!invites.data?.length && (
        <table className="table" data-testid="invites-table">
          <thead><tr><th>Email</th><th>Role</th><th>Status</th><th>Expires</th><th /></tr></thead>
          <tbody>
            {invites.data.map((i) => (
              <tr key={i.id}>
                <td>{i.email}</td><td>{i.role}</td>
                <td><span className={`pill ${i.state === 'pending' ? 'pending' : 'failed'}`}>{i.state}</span></td>
                <td className="small">{new Date(i.expires_at).toLocaleDateString()}</td>
                <td><button className="link" onClick={() => revoke.mutate(i.id)}>Revoke</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

const ACTIONS: Record<string, string> = {
  'invite.created': 'Invite created', 'invite.revoked': 'Invite revoked', 'invite.accepted': 'Joined',
  'member.role_changed': 'Role changed', 'member.removed': 'Member removed', 'settings.updated': 'Settings changed',
  'recording.deleted': 'Audio deleted (retention)',
}

function AuditLog() {
  const events = useQuery({ queryKey: ['audit'], queryFn: Api.audit })
  return (
    <section>
      <h2>Audit log</h2>
      {!events.data?.length && <p className="muted">Nothing yet.</p>}
      {!!events.data?.length && (
        <div className="table-wrap">
          <table className="table" data-testid="audit-table">
            <thead><tr><th>When</th><th>What</th><th>Detail</th></tr></thead>
            <tbody>
              {events.data.map((e) => (
                <tr key={e.id}>
                  <td className="small">{new Date(e.created_at).toLocaleString()}</td>
                  <td>{ACTIONS[e.action] ?? e.action}{!e.actor_user_id && <span className="muted small"> · system</span>}</td>
                  <td className="small muted">{describe(e.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function describe(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .map(([k, v]) => (v && typeof v === 'object' && 'to' in v ? `${k}: ${String((v as any).from)} → ${String((v as any).to)}` : `${k}: ${String(v)}`))
    .join(' · ')
}
