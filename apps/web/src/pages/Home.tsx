import { useQuery } from '@tanstack/react-query'
import { Api, type Scenario } from '../api/client'

const DIFFICULTY: Record<string, string> = { easy: 'Easy', medium: 'Medium', hard: 'Hard' }

export function HomePage() {
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: Api.scenarios })
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: Api.sessions })
  const byId = new Map((scenarios.data ?? []).map((s) => [s.id, s]))

  return (
    <>
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
