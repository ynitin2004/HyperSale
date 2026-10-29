// The roleplay screen (DESIGN §2): preflight -> connecting -> live -> ending -> report.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Api, ApiError } from '../api/client'
import { navigate } from '../router'
import { rms, startStubCall, startWebrtcCall, type ActiveCall, type CallState, type LiveTurn } from '../voice/call'

type Phase = 'preflight' | CallState

export function PracticePage({ scenarioId }: { scenarioId: string }) {
  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: Api.scenarios })
  const config = useQuery({ queryKey: ['config'], queryFn: Api.config })
  const scenario = scenarios.data?.find((s) => s.id === scenarioId)
  const stub = config.data?.voice_provider === 'stub'

  const [phase, setPhase] = useState<Phase>('preflight')
  const [detail, setDetail] = useState<string | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [turns, setTurns] = useState<LiveTurn[]>([])
  const [mic, setMic] = useState<MediaStream | null>(null)
  const [micError, setMicError] = useState<string | null>(null)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState<string>('')
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [cap, setCap] = useState(300)
  const [now, setNow] = useState(Date.now())
  const call = useRef<ActiveCall | null>(null)
  const ending = useRef(false)

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 500)
    return () => window.clearInterval(t)
  }, [])

  // Leaving the page mid-call still ends it, so the report and the ledger stay complete.
  useEffect(() => () => void call.current?.end('rep_left').catch(() => undefined), [])

  async function enableMic(id?: string) {
    setMicError(null)
    mic?.getTracks().forEach((t) => t.stop())
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: id ? { exact: id } : undefined, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      setMic(stream)
      const all = await navigator.mediaDevices.enumerateDevices()
      setDevices(all.filter((d) => d.kind === 'audioinput'))
    } catch (err) {
      const name = err instanceof DOMException ? err.name : ''
      setMicError(
        name === 'NotAllowedError'
          ? 'Microphone access is blocked. Click the lock icon in the address bar, allow the microphone, then try again.'
          : name === 'NotFoundError'
            ? 'No microphone was found. Plug one in and try again.'
            : `Could not open the microphone (${name || 'unknown error'}).`,
      )
    }
  }

  async function start() {
    if (!scenario) return
    setPhase('connecting')
    try {
      const session = await Api.createSession(scenario.id)
      const callbacks = {
        onState: (s: CallState, d?: string) => {
          setPhase(s)
          setDetail(d ?? null)
        },
        onTurns: setTurns,
        onBanner: setBanner,
        onAudioEvent: (e: string) => console.debug('[audio]', e),
      }
      const active = stub ? await startStubCall(session.id, callbacks) : await startWebrtcCall(session.id, mic!, callbacks)
      call.current = active
      setCap(active.capSeconds)
      setStartedAt(Date.now())
    } catch (err) {
      setPhase('failed')
      setDetail(err instanceof ApiError ? `${err.message} (${err.code})` : String(err))
    }
  }

  async function end() {
    if (!call.current || ending.current) return
    ending.current = true
    try {
      const reportId = await call.current.end('rep_ended')
      call.current = null
      mic?.getTracks().forEach((t) => t.stop())
      if (reportId) navigate(`/report/${reportId}`)
      else navigate('/')
    } catch (err) {
      setPhase('failed')
      setDetail(String(err))
    }
  }

  const elapsed = startedAt ? Math.floor((now - startedAt) / 1000) : 0
  // The server hangs up at the cap (D29); mirror it so the rep is never surprised.
  useEffect(() => {
    if (startedAt && elapsed >= cap && (phase === 'live' || phase === 'degraded')) void end()
  })

  if (!scenario) return <p className="muted">{scenarios.isLoading ? 'Loading…' : 'Scenario not found.'}</p>

  return (
    <div className="practice">
      <section className="card brief">
        <p className="eyebrow">{scenario.call_type.replace(/_/g, ' ')} · {scenario.difficulty}</p>
        <h2>{scenario.title}</h2>
        <p><strong>{scenario.persona_name}</strong>, {scenario.persona_title} — {scenario.persona_company}</p>
        <p className="muted">{scenario.brief}</p>
        <p className="small muted">Scored on: {scenario.applicable_criteria.join(', ').replace(/_/g, ' ')}</p>
      </section>

      {phase === 'preflight' && (
        <section className="card" data-testid="preflight">
          <h3>Preflight</h3>
          {stub ? (
            <p className="muted">Demo mode: the buyer is scripted and no microphone is needed.</p>
          ) : (
            <>
              <p className="muted">Allow your microphone and speak — the bar should move. Headphones stop echo.</p>
              {!mic && <button onClick={() => enableMic()} data-testid="enable-mic">Enable microphone</button>}
              {micError && <p className="error" role="alert" data-testid="mic-error">{micError}</p>}
              {mic && (
                <>
                  {devices.length > 1 && (
                    <label>Microphone
                      <select value={deviceId} onChange={(e) => (setDeviceId(e.target.value), enableMic(e.target.value))}>
                        {devices.map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || 'Microphone'}</option>)}
                      </select>
                    </label>
                  )}
                  <MicMeter stream={mic} />
                  <button className="ghost" onClick={playTestTone}>Play test tone</button>
                </>
              )}
            </>
          )}
          <button onClick={start} disabled={!stub && !mic} data-testid="start-call">Start call</button>
        </section>
      )}

      {phase !== 'preflight' && (
        <section className="card live" data-testid="live">
          <div className="live-head">
            <span className={`state ${phase}`} data-testid="call-state">{LABEL[phase]}</span>
            <span className="muted" data-testid="elapsed">{fmt(elapsed)} / {fmt(cap)}</span>
            {mic && phase === 'live' && <MicMeter stream={mic} compact />}
            {(phase === 'live' || phase === 'degraded') && (
              <button className="danger" onClick={end} data-testid="end-call">End call</button>
            )}
          </div>
          {detail && <p className={phase === 'failed' ? 'error' : 'muted'}>{detail}</p>}
          {banner && <p className="banner" role="status">{banner}</p>}
          {phase === 'ending' && <p className="muted">Saving the call and computing your metrics…</p>}
          <ol className="transcript live-transcript" data-testid="live-transcript">
            {turns.map((t) => (
              <li key={t.id} className={t.speaker}>
                <span className="who">{t.speaker === 'rep' ? 'You' : scenario.persona_name}</span>
                <span className={t.final ? '' : 'muted'}>{t.text}</span>
              </li>
            ))}
            {!turns.length && phase === 'live' && <li className="muted">Say hello — {scenario.persona_name} is on the line.</li>}
          </ol>
          {phase === 'failed' && <button onClick={() => navigate('/')}>Back to scenarios</button>}
        </section>
      )}
    </div>
  )
}

const LABEL: Record<Phase, string> = {
  preflight: 'Ready', connecting: 'Connecting…', live: 'Live', degraded: 'Reconnecting…',
  ending: 'Ending…', ended: 'Ended', failed: 'Failed',
}

function fmt(s: number) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function playTestTone() {
  const ctx = new AudioContext()
  const osc = ctx.createOscillator()
  osc.frequency.value = 440
  osc.connect(ctx.destination)
  osc.start()
  osc.stop(ctx.currentTime + 0.4)
  osc.onended = () => void ctx.close()
}

function MicMeter({ stream, compact = false }: { stream: MediaStream; compact?: boolean }) {
  const [level, setLevel] = useState(0)
  useEffect(() => {
    const ctx = new AudioContext()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    ctx.createMediaStreamSource(stream).connect(analyser)
    const buf = new Float32Array(analyser.fftSize)
    const t = window.setInterval(() => setLevel(Math.min(1, rms(analyser, buf) * 8)), 100)
    return () => {
      window.clearInterval(t)
      void ctx.close()
    }
  }, [stream])
  return (
    <div className={`meter ${compact ? 'compact' : ''}`} aria-label="Microphone level" data-testid="mic-meter">
      <div style={{ width: `${Math.round(level * 100)}%` }} />
    </div>
  )
}
