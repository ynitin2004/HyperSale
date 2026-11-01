// Recording review (M3, D43): upload a real call and get the same report as a roleplay.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Api, ApiError } from '../api/client'
import { navigate } from '../router'

// Below the bucket's 2 MB object limit (D31).
const CHUNK_BYTES = 1_500_000
const MAX_BYTES = 100_000_000
const POLL_MS = 1500

async function waitForReport(id: string): Promise<string> {
  for (;;) {
    const row = await Api.session(id)
    if (row.report_id) return row.report_id
    if (row.status === 'failed') {
      throw new Error(row.end_reason === 'one_speaker'
        ? 'Only one voice was found. Scoring needs both sides of the call.'
        : 'We could not transcribe this recording.')
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS))
  }
}

export function ReviewPage() {
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: Api.scenarios })
  const [scenarioId, setScenarioId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [repFirst, setRepFirst] = useState(true)
  const [consent, setConsent] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const busy = progress !== ''

  async function upload() {
    if (!file) return
    if (file.size > MAX_BYTES) {
      setError('This recording is over the 100 MB limit.')
      return
    }
    setError('')
    try {
      setProgress('Uploading…')
      const { id } = await Api.createReview({ scenario_id: scenarioId, rep_speaks_first: repFirst, consent })
      const chunks = Math.ceil(file.size / CHUNK_BYTES)
      for (let seq = 0; seq < chunks; seq++) {
        const start = seq * CHUNK_BYTES
        await Api.uploadChunk(id, seq, file.slice(start, start + CHUNK_BYTES, file.type))
        setProgress(`Uploading… ${Math.round(((seq + 1) / chunks) * 100)}%`)
      }
      await Api.submitReview(id)
      setProgress('Transcribing the call…')
      navigate(`/report/${await waitForReport(id)}`)
    } catch (err) {
      setProgress('')
      setError(err instanceof ApiError ? err.message : String(err instanceof Error ? err.message : err))
    }
  }

  return (
    <section data-testid="review">
      <h2>Review a real call</h2>
      <p className="muted">Upload a recording with two speakers and get a scored report, with every quote checked against the transcript.</p>
      <p>
        <label>Scored as{' '}
          <select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} data-testid="review-scenario">
            <option value="">Choose the closest scenario</option>
            {(scenarios.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select>
        </label>
      </p>
      <p>
        <label>Recording{' '}
          <input type="file" accept="audio/*,video/webm" data-testid="review-file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
      </p>
      <p>
        <label>Who speaks first?{' '}
          <select value={repFirst ? 'rep' : 'buyer'} onChange={(e) => setRepFirst(e.target.value === 'rep')} data-testid="review-first">
            <option value="rep">The rep</option>
            <option value="buyer">The buyer</option>
          </select>
        </label>
      </p>
      <p>
        <label>
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} data-testid="review-consent" />
          {' '}I have permission from everyone on this call to upload it.
        </label>
      </p>
      <button disabled={busy || !file || !scenarioId || !consent} onClick={upload} data-testid="review-upload">Score this call</button>
      {progress && <p className="muted" data-testid="review-progress">{progress}</p>}
      {error && <p className="error" data-testid="review-error">{error}</p>}
    </section>
  )
}
