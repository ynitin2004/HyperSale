import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Api, ApiError, type MemberSummary } from '../api/client'

// D39: the manager loop - who is practising, how they score per criterion, what is assigned.
const CRITERIA = ['opening', 'discovery', 'listening', 'value', 'objection_handling', 'next_step', 'positioning']

export function TeamPage() {
  const team = useQuery({ queryKey: ['team'], queryFn: Api.team, retry: false })
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: Api.scenarios })
  const assignments = useQuery({ queryKey: ['assignments'], queryFn: Api.assignments })
  const [selected, setSelected] = useState<string | null>(null)

  if (team.error instanceof ApiError && team.error.status === 403)
    return <p className="muted">The team view is for managers.</p>
  if (team.error) return <p className="error">Could not load the team: {String(team.error)}</p>
  if (!team.data) return <p className="muted">Loading team…</p>

  const name = (m: { user_id: string; email?: string | null }) => m.email ?? `member ${m.user_id.slice(0, 8)}`
  const byUser = new Map(team.data.map((m) => [m.user_id, m]))
  const scenarioTitle = new Map((scenarios.data ?? []).map((s) => [s.id, s.title]))

  return (
    <>
      <section>
        <h2>Team comparison</h2>
        <p className="muted">Mean scores across each member's scored calls. Click a member to review their attempts.</p>
        <div className="table-wrap">
          <table className="table" data-testid="team-table">
            <thead>
              <tr><th>Member</th><th>Attempts</th><th>Mean</th>
                {CRITERIA.map((c) => <th key={c} className="small">{c.replace('_', ' ')}</th>)}
                <th>Open</th></tr>
            </thead>
            <tbody>
              {team.data.map((m) => (
                <tr key={m.user_id} className={selected === m.user_id ? 'selected' : ''}>
                  <td><button className="link" onClick={() => setSelected(m.user_id)}>{name(m)}</button>
                    <span className="muted small"> {m.role}</span></td>
                  <td>{m.attempts}</td>
                  <td><strong>{m.mean_overall?.toFixed(1) ?? '—'}</strong></td>
                  {CRITERIA.map((c) => <td key={c}>{m.criteria[c]?.toFixed(1) ?? '—'}</td>)}
                  <td>{m.open_assignments || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected && byUser.get(selected) && <Attempts member={byUser.get(selected)!} label={name(byUser.get(selected)!)} titles={scenarioTitle} />}

      <AssignForm members={team.data} />

      <section>
        <h2>Assignments</h2>
        {!assignments.data?.length && <p className="muted">Nothing assigned yet.</p>}
        {!!assignments.data?.length && (
          <table className="table" data-testid="assignment-table">
            <thead><tr><th>Member</th><th>Scenario</th><th>Due</th><th>Status</th><th /></tr></thead>
            <tbody>
              {assignments.data.map((a) => (
                <tr key={a.id}>
                  <td>{byUser.get(a.assignee_user_id) ? name(byUser.get(a.assignee_user_id)!) : a.assignee_user_id.slice(0, 8)}</td>
                  <td>{scenarioTitle.get(a.scenario_id) ?? '—'}</td>
                  <td>{a.due_at ? new Date(a.due_at).toLocaleDateString() : '—'}</td>
                  <td>{a.completed_report_id ? <span className="pill ready">done {a.overall?.toFixed(1)}</span> : <span className="pill pending">open</span>}</td>
                  <td>{a.completed_report_id && <a href={`#/report/${a.completed_report_id}`}>Report →</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}

function Attempts({ member, label, titles }: { member: MemberSummary; label: string; titles: Map<string, string> }) {
  const attempts = useQuery({ queryKey: ['member-sessions', member.user_id], queryFn: () => Api.memberSessions(member.user_id) })
  return (
    <section data-testid="member-attempts">
      <h2>{label}: attempts</h2>
      {!attempts.data?.length && <p className="muted">No calls yet.</p>}
      {!!attempts.data?.length && (
        <table className="table">
          <thead><tr><th>Scenario</th><th>When</th><th>Status</th><th>Score</th><th /></tr></thead>
          <tbody>
            {attempts.data.map((s) => (
              <tr key={s.id}>
                <td>{titles.get(s.scenario_id) ?? '—'}</td>
                <td>{new Date(s.created_at).toLocaleString()}</td>
                <td><span className={`pill ${s.report_status ?? s.status}`}>{s.report_status ?? s.status}</span></td>
                <td>{s.overall != null ? s.overall.toFixed(1) : '—'}</td>
                <td>{s.report_id && <a href={`#/report/${s.report_id}`}>Review →</a>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function AssignForm({ members }: { members: MemberSummary[] }) {
  const qc = useQueryClient()
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: Api.scenarios })
  const [assignee, setAssignee] = useState('')
  const [scenario, setScenario] = useState('')
  const [due, setDue] = useState('')
  const [note, setNote] = useState('')
  const assign = useMutation({
    mutationFn: () => Api.assign({ assignee_user_id: assignee, scenario_id: scenario,
      due_at: due ? new Date(due).toISOString() : null, note: note || null }),
    onSuccess: () => { setNote(''); qc.invalidateQueries({ queryKey: ['assignments'] }); qc.invalidateQueries({ queryKey: ['team'] }) },
  })
  return (
    <section>
      <h2>Assign a scenario</h2>
      <form className="card form inline" data-testid="assign-form" onSubmit={(e) => { e.preventDefault(); assign.mutate() }}>
        <select required value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Member">
          <option value="">Member…</option>
          {members.map((m) => <option key={m.user_id} value={m.user_id}>{m.email ?? m.user_id.slice(0, 8)}</option>)}
        </select>
        <select required value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="Scenario">
          <option value="">Scenario…</option>
          {(scenarios.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
        </select>
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="Due date" />
        <input placeholder="Note (optional)" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        <button type="submit" disabled={assign.isPending}>{assign.isPending ? 'Assigning…' : 'Assign'}</button>
        {assign.error && <p className="error">{String(assign.error)}</p>}
        {assign.isSuccess && <p className="muted" role="status">Assigned.</p>}
      </form>
    </section>
  )
}
