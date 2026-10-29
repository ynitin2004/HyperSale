// Report page (DESIGN §2.5, §5). Metrics render instantly; criteria arrive when scoring
// lands; every quote is speaker-labelled and seeks the recording to its moment.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Api, type Criterion, type Evidence, type Report } from '../api/client'

const FINAL = new Set(['ready', 'degraded', 'failed'])
const SEEK_LEAD_MS = 300

export function ReportPage({ reportId }: { reportId: string }) {
  const report = useQuery({
    queryKey: ['report', reportId],
    queryFn: () => Api.report(reportId),
    refetchInterval: (q) => (q.state.data && FINAL.has(q.state.data.status) ? false : 1000),
  })
  const r = report.data
  const transcript = useQuery({
    queryKey: ['transcript', r?.session_id],
    queryFn: () => Api.transcript(r!.session_id),
    enabled: !!r,
  })
  const [active, setActive] = useState<{ turn: number; key: string } | null>(null)
  const audio = useRecording(r)

  const moments = useMemo(
    () => (r?.criteria ?? []).flatMap((c) => c.evidence.map((e, i) => ({ key: `${c.criterion_id}-${i}`, e }))),
    [r],
  )

  function seek(e: Evidence, key: string) {
    setActive({ turn: e.turn_index, key })
    document.getElementById(`turn-${e.turn_index}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    const el = audio.ref.current
    if (el && audio.url) {
      const offset = r?.recorder_offset_ms ?? 0
      el.currentTime = Math.max(0, (e.start_ms - offset - SEEK_LEAD_MS) / 1000)
      void el.play().catch(() => undefined)
    }
  }

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (!moments.length || (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft')) return
      const i = moments.findIndex((m) => m.key === active?.key)
      const next = ev.key === 'ArrowRight' ? Math.min(moments.length - 1, i + 1) : Math.max(0, i - 1)
      seek(moments[next].e, moments[next].key)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (report.isLoading) return <p className="muted">Loading report…</p>
  if (report.error || !r) return <p className="error">Could not load this report: {String(report.error)}</p>
  const pending = !FINAL.has(r.status)

  return (
    <div className="report" data-testid="report">
      <header className="report-head">
        <div>
          <p className="eyebrow">{r.persona_name}</p>
          <h2>{r.scenario_title}</h2>
        </div>
        <div className="overall" data-testid="overall">
          {r.overall != null ? <><strong>{r.overall.toFixed(1)}</strong><span>/ 5</span></> : <span className="muted">{pending ? '…' : '—'}</span>}
        </div>
      </header>

      <MetricsStrip metrics={r.metrics} />

      {pending && <ScoringProgress report={r} />}
      {r.status === 'degraded' && (
        <p className="banner" data-testid="degraded">Some evidence could not be verified after retries, so it was removed and those criteria are flagged. Nothing unverified is shown as fact.</p>
      )}
      {r.status === 'failed' && <p className="error" data-testid="failed">Scoring failed: {r.error}. Your transcript and metrics are saved.</p>}

      <div className="report-grid">
        <section>
          <h3>Criteria</h3>
          <div className="criteria" data-testid="criteria">
            {r.criteria.map((c) => <CriterionCard key={c.criterion_id} c={c} active={active?.key} onSeek={seek} />)}
            {pending && r.pending_criteria.map((id) => <div key={id} className="card criterion skeleton">{id.replace(/_/g, ' ')}</div>)}
          </div>

          {!!r.drills.length && (
            <>
              <h3>Practice next</h3>
              <ol className="drills" data-testid="drills">
                {r.drills.map((d) => <li key={d.id}><strong>{d.title}</strong><span className="muted"> — {d.instructions}</span></li>)}
              </ol>
            </>
          )}
        </section>

        <aside>
          <h3>Recording</h3>
          {r.recording_available ? (
            audio.url ? <audio ref={audio.ref} src={audio.url} controls data-testid="recording" /> : <p className="muted">Loading audio…</p>
          ) : (
            <p className="muted" data-testid="no-audio">Audio unavailable — this report is transcript-based.</p>
          )}
          <h3>Transcript</h3>
          <ol className="transcript" data-testid="transcript">
            {(transcript.data ?? []).map((t) => (
              <li key={t.idx} id={`turn-${t.idx}`} className={`${t.speaker} ${active?.turn === t.idx ? 'hit' : ''}`}>
                <span className="who">{t.speaker === 'rep' ? 'You' : r.persona_name}</span>
                <span className="ts">{fmtMs(t.start_ms)}</span>
                <span>{t.text}</span>
              </li>
            ))}
          </ol>
        </aside>
      </div>

      <footer className="provenance small muted" data-testid="provenance">
        Scored with {r.provenance.model_id ?? '—'} · prompt {r.provenance.prompt_version ?? '—'} · {r.provenance.rubric_version} ·
        {' '}{r.provenance.metrics_version} · persona prompt {r.provenance.persona_prompt_version}
        {typeof r.timings.end_to_report_ms === 'number' && <> · report in {(r.timings.end_to_report_ms / 1000).toFixed(1)} s</>}
      </footer>
    </div>
  )
}

function CriterionCard({ c, active, onSeek }: { c: Criterion; active?: string; onSeek: (e: Evidence, key: string) => void }) {
  const insufficient = c.outcome === 'insufficient_evidence'
  return (
    <article className={`card criterion ${insufficient ? 'neutral' : ''}`} data-testid={`criterion-${c.criterion_id}`}>
      <header>
        <h4>{c.name}</h4>
        {insufficient ? (
          <span className="pill neutral" title="This call never reached a point where this could be observed">Not observed</span>
        ) : (
          <span className={`score s${c.score}`}>{c.score}</span>
        )}
      </header>
      {!c.verified && <p className="small warn">Evidence for this criterion could not be fully verified.</p>}
      <p>{c.rationale}</p>
      {c.evidence.map((e, i) => {
        const key = `${c.criterion_id}-${i}`
        return (
          <button key={key} className={`quote ${active === key ? 'active' : ''}`} onClick={() => onSeek(e, key)} data-testid="evidence">
            <span className="who">{e.speaker === 'rep' ? 'You said' : 'Buyer said'} · {fmtMs(e.start_ms)}</span>
            “{e.quote}”
          </button>
        )
      })}
      {insufficient && <p className="small muted">Not scored and not counted in your average — the call didn't reach this point.</p>}
    </article>
  )
}

function MetricsStrip({ metrics }: { metrics: Record<string, unknown> }) {
  const m = metrics as Record<string, number | boolean | null>
  const items: [string, string][] = [
    ['Talk ratio (you)', m.talk_ratio_rep != null ? `${Math.round((m.talk_ratio_rep as number) * 100)}%` : '—'],
    ['Questions asked', `${m.questions ?? 0} (${m.open_questions ?? 0} open)`],
    ['Longest monologue', `${m.longest_monologue_words ?? 0} words`],
    ['Fillers / 100 words', `${m.fillers_per_100_words ?? 0}`],
    ['Next step with a date', m.next_step_with_date ? 'Yes' : 'No'],
    ['Duration', fmtMs((m.duration_ms as number) ?? 0)],
  ]
  return (
    <div className="metrics" data-testid="metrics">
      {items.map(([k, v]) => <div key={k}><span>{k}</span><strong>{v}</strong></div>)}
    </div>
  )
}

function ScoringProgress({ report }: { report: Report }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(t)
  }, [])
  const s = Math.max(0, Math.floor((now - Date.parse(report.created_at)) / 1000))
  return (
    <p className="banner" data-testid="scoring-progress">
      Scoring {report.pending_criteria.length} criteria and verifying every quote against the transcript… {s}s
      {s > 30 && ' — taking longer than usual, still working.'}
    </p>
  )
}

function useRecording(r: Report | undefined) {
  const ref = useRef<HTMLAudioElement>(null)
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!r?.recording_available) return
    let revoked = false
    let objectUrl: string | null = null
    Api.recording(r.session_id)
      .then((blob) => {
        if (revoked) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => setUrl(null))
    return () => {
      revoked = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [r?.session_id, r?.recording_available])
  // MediaRecorder WebM carries no duration, which breaks seeking until the browser has
  // scanned to the end once; force that scan as soon as metadata loads.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const fix = () => {
      if (el.duration === Infinity) {
        el.currentTime = 1e101
        el.addEventListener('timeupdate', () => (el.currentTime = 0), { once: true })
      }
    }
    el.addEventListener('loadedmetadata', fix)
    return () => el.removeEventListener('loadedmetadata', fix)
  }, [url])
  return { ref, url }
}

function fmtMs(ms: number) {
  const s = Math.floor(ms / 1000)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
