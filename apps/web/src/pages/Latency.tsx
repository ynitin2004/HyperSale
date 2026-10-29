// Latency dashboard (PHASES M1 "latency dashboard live"; ARCHITECTURE §5 budgets).
import { useQuery } from '@tanstack/react-query'
import { Api } from '../api/client'

export function LatencyPage() {
  const stages = useQuery({ queryKey: ['latency'], queryFn: Api.latency, refetchInterval: 10_000 })
  const integrity = useQuery({ queryKey: ['integrity'], queryFn: Api.integrity })
  return (
    <section data-testid="latency">
      <h2>Latency against budget</h2>
      <p className="muted">Measured on every call in this workspace. p95 must sit under the budget line.</p>
      <table className="table">
        <thead><tr><th>Stage</th><th>Samples</th><th>p50</th><th>p95</th><th>Budget</th><th>Status</th><th>Recent</th></tr></thead>
        <tbody>
          {(stages.data ?? []).map((s) => (
            <tr key={s.key} data-testid={`stage-${s.key}`}>
              <td>{s.label}</td>
              <td>{s.samples}</td>
              <td>{ms(s.p50_ms)}</td>
              <td>{ms(s.p95_ms)}</td>
              <td>{ms(s.budget_ms)}</td>
              <td>{s.within_budget == null ? <span className="muted">no data</span> : s.within_budget ? <span className="ok">within</span> : <span className="error">over</span>}</td>
              <td><Spark values={s.recent} budget={s.budget_ms} /></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Evidence integrity</h2>
      {integrity.data && (
        <p data-testid="integrity">
          {integrity.data.quotes_checked} persisted quotes across {integrity.data.reports} reports re-verified against their transcripts:{' '}
          <strong className={integrity.data.quotes_failing ? 'error' : 'ok'}>{integrity.data.quotes_failing} failing</strong>.
        </p>
      )}
    </section>
  )
}

function ms(v: number | null | undefined) {
  if (v == null) return '—'
  return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`
}

function Spark({ values, budget }: { values: number[]; budget: number }) {
  if (!values.length) return null
  const max = Math.max(budget, ...values)
  const pts = [...values].reverse()
  return (
    <svg width="120" height="28" viewBox={`0 0 ${pts.length * 6} 28`} preserveAspectRatio="none" aria-hidden>
      <line x1="0" x2={pts.length * 6} y1={28 - (budget / max) * 26} y2={28 - (budget / max) * 26} className="budget" />
      {pts.map((v, i) => (
        <rect key={i} x={i * 6} width="4" y={28 - (v / max) * 26} height={(v / max) * 26} className={v > budget ? 'over' : ''} />
      ))}
    </svg>
  )
}
