import { useQuery } from '@tanstack/react-query'
import { Api, type Scenario } from '../api/client'

const DIFFICULTY: Record<string, string> = { easy: 'Easy', medium: 'Medium', hard: 'Hard' }

export function HomePage() {
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: Api.scenarios })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: Api.sessions })
  const assignments = useQuery({ queryKey: ['assignments'], queryFn: Api.assignments })
  const me = useQuery({ queryKey: ['me'], queryFn: Api.me, retry: false })
  const byId = new Map((scenarios.data ?? []).map((s) => [s.id, s]))
  const mine = (assignments.data ?? []).filter((a) => a.assignee_user_id === me.data?.user_id)

  return (
    <>
      {mine.length > 0 && (
        <section data-testid="my-assignments">
          <h2>Assigned to you</h2>
          <ul className="assignments">
            {mine.map((a) => (
              <li key={a.id}>
                <a href={`#/practice/${a.scenario_id}`}>{byId.get(a.scenario_id)?.title ?? 'Scenario'}</a>
                {a.due_at && <span className="muted small"> · due {new Date(a.due_at).toLocaleDateString()}</span>}
                {a.note && <span className="muted small"> · {a.note}</span>}
                {a.completed_report_id
                  ? <a className="pill ready" href={`#/report/${a.completed_report_id}`}>done {a.overall?.toFixed(1)}</a>
                  : <span className="pill pending">to do</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h2>Pick a buyer</h2>
        <p className="muted">Five hand-built personas. Each scenario is scored only on the criteria it can actually show.</p>
        {scenarios.isLoading && <p className="muted">Loading scenarios…</p>}
        {scenarios.error && <p className="error">Could not load scenarios: {String(scenarios.error)}</p>}
        <div className="grid" data-testid="scenario-list">
          {(scenarios.data ?? []).map((s) => <ScenarioCard key={s.id} s={s} />)}
        </div>
      </section>

      <section>
        <h2>Your recent calls</h2>
        {sessions.data?.length === 0 && <p className="muted">No calls yet — start with the highlighted scenario.</p>}
        {!!sessions.data?.length && (
          <table className="table" data-testid="history">
            <thead><tr><th>Scenario</th><th>When</th><th>Status</th><th>Score</th><th /></tr></thead>
            <tbody>
              {sessions.data.map((s) => (
                <tr key={s.id}>
                  <td>{byId.get(s.scenario_id)?.title ?? '—'}</td>
                  <td>{new Date(s.created_at).toLocaleString()}</td>
                  <td><span className={`pill ${s.report_status ?? s.status}`}>{s.report_status ?? s.status}</span></td>
                  <td>{s.overall != null ? s.overall.toFixed(1) : '—'}</td>
                  <td>{s.report_id && <a href={`#/report/${s.report_id}`}>Report →</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}

function ScenarioCard({ s }: { s: Scenario }) {
  return (
    <a className={`card scenario ${s.featured ? 'featured' : ''}`} href={`#/practice/${s.id}`} data-testid={`scenario-${s.slug}`}>
      {s.featured && <span className="badge">Try this first</span>}
      <h3>{s.title}</h3>
      <p className="muted small">{s.persona_name} · {s.persona_title}, {s.persona_company}</p>
      <p>{s.brief}</p>
      <p className="small"><span className={`pill ${s.difficulty}`}>{DIFFICULTY[s.difficulty] ?? s.difficulty}</span> {s.applicable_criteria.length} criteria</p>
    </a>
  )
}
