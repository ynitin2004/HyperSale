// The browser half of a roleplay (FLOW chain B, D29).
//
// WebRTC mode: the browser makes an SDP offer, the api relays it to Azure Voice Live with
// the server-held key and returns the answer. Media then flows browser<->Azure directly;
// the api holds the signalling socket for the call's life and captures the authoritative
// transcript. The data channel gives this page a live transcript with no server hop.
//
// Stub mode (D31): no media. The api runs a scripted call; this page polls the transcript.
import { Api } from '../api/client'

export type CallState = 'connecting' | 'live' | 'degraded' | 'ending' | 'ended' | 'failed'
export type LiveTurn = { id: string; speaker: 'rep' | 'buyer'; text: string; final: boolean }

export type CallCallbacks = {
  onState: (state: CallState, detail?: string) => void
  onTurns: (turns: LiveTurn[]) => void
  onBanner: (message: string | null) => void
  onAudioEvent?: (event: string) => void
}

export type ActiveCall = {
  mode: 'webrtc' | 'stub'
  capSeconds: number
  end: (reason?: 'rep_ended' | 'rep_left' | 'client_error') => Promise<string | null>
}

const CHUNK_MS = 10_000
const SILENT_RMS = 0.004
const SILENT_WARN_MS = 5_000

export function rms(analyser: AnalyserNode, buf: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(buf)
  let sum = 0
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
  return Math.sqrt(sum / buf.length)
}

class TranscriptModel {
  private turns = new Map<string, LiveTurn>()
  private order: string[] = []
  constructor(private emit: (t: LiveTurn[]) => void) {}
  upsert(id: string, speaker: 'rep' | 'buyer', text: string, final: boolean, append = false) {
    const prev = this.turns.get(id)
    if (!prev) this.order.push(id)
    this.turns.set(id, { id, speaker, final, text: append && prev ? prev.text + text : text })
    this.emit(this.order.map((k) => this.turns.get(k)!))
  }
}

export async function startWebrtcCall(
  sessionId: string,
  mic: MediaStream,
  cb: CallCallbacks,
): Promise<ActiveCall> {
  cb.onState('connecting')
  const transcript = new TranscriptModel(cb.onTurns)
  const pc = new RTCPeerConnection()
  const audioEl = new Audio()
  audioEl.autoplay = true
  audioEl.dataset.testid = 'buyer-audio'
  document.body.appendChild(audioEl)

  const ctx = new AudioContext()
  await ctx.resume() // started from the Start click, so autoplay policy allows it
  const dest = ctx.createMediaStreamDestination()
  const micSource = ctx.createMediaStreamSource(mic)
  micSource.connect(dest)
  const micAnalyser = ctx.createAnalyser()
  micAnalyser.fftSize = 1024
  micSource.connect(micAnalyser)

  let recorder: MediaRecorder | null = null
  let seq = 0
  let uploads = Promise.resolve()
  let uploadFailures = 0
  let serverOpenAt = 0
  let recorderOffsetMs: number | null = null
  // D32: Voice Live sends usage and speech/response start events only on this data
  // channel, so the page measures them and hands them to the api at hang-up.
  const turnStarts: Record<string, number> = {}
  const usage = { text_in: 0, text_in_cached: 0, audio_in: 0, audio_in_cached: 0, text_out: 0, audio_out: 0, responses: 0 }
  const markStart = (itemId?: string) => {
    if (itemId && serverOpenAt && turnStarts[itemId] === undefined) {
      turnStarts[itemId] = Math.max(0, Math.round(performance.now() - serverOpenAt))
    }
  }
  const addUsage = (u: any) => {
    const ind = u?.input_token_details ?? {}
    const outd = u?.output_token_details ?? {}
    const cached = ind.cached_tokens_details ?? {}
    usage.text_in += Math.max(0, (ind.text_tokens ?? 0) - (cached.text_tokens ?? 0))
    usage.audio_in += Math.max(0, (ind.audio_tokens ?? 0) - (cached.audio_tokens ?? 0))
    usage.text_in_cached += cached.text_tokens ?? 0
    usage.audio_in_cached += cached.audio_tokens ?? 0
    usage.text_out += outd.text_tokens ?? 0
    usage.audio_out += outd.audio_tokens ?? 0
    usage.responses += 1
  }

  const startRecorder = (remote: MediaStream) => {
    ctx.createMediaStreamSource(remote).connect(dest)
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find((t) => MediaRecorder.isTypeSupported(t))
    if (!mime) {
      cb.onBanner('This browser cannot record the call; the report will be transcript-only.')
      return
    }
    recorder = new MediaRecorder(dest.stream, { mimeType: mime, audioBitsPerSecond: 24_000 })
    recorder.ondataavailable = (e) => {
      if (!e.data.size) return
      const n = seq++
      // Sequential uploads keep chunk order; a failed chunk is reported, never fatal.
      uploads = uploads.then(() =>
        Api.uploadChunk(sessionId, n, e.data).catch(() => {
          uploadFailures++
          cb.onAudioEvent?.(`upload chunk ${n} failed`)
        }),
      )
    }
    recorder.start(CHUNK_MS)
    recorderOffsetMs = Math.round(performance.now() - serverOpenAt)
    cb.onAudioEvent?.(`recorder started ${mime}`)
  }

  pc.ontrack = (e) => {
    audioEl.srcObject = e.streams[0]
    audioEl.play().catch(() => cb.onBanner('Your browser blocked audio. Click anywhere to hear the buyer.'))
    cb.onAudioEvent?.('remote track received')
    startRecorder(e.streams[0])
  }
  pc.onconnectionstatechange = () => {
    cb.onAudioEvent?.(`webrtc ${pc.connectionState}`)
    if (pc.connectionState === 'connected') cb.onState('live')
    if (pc.connectionState === 'disconnected') cb.onState('degraded', 'Network trouble, trying to recover…')
    if (pc.connectionState === 'failed') cb.onState('failed', 'The connection to the buyer was lost.')
  }
  mic.getTracks().forEach((t) => pc.addTrack(t, mic))

  const dc = pc.createDataChannel('voice-live-events')
  dc.onmessage = (e) => {
    let m: any
    try {
      m = JSON.parse(e.data)
    } catch {
      return
    }
    switch (m.type) {
      case 'input_audio_buffer.speech_started':
        markStart(m.item_id)
        break
      case 'response.output_item.added':
        markStart(m.item?.id)
        break
      case 'response.done':
        if (m.response?.usage) addUsage(m.response.usage)
        break
      case 'conversation.item.input_audio_transcription.completed':
        transcript.upsert(m.item_id, 'rep', (m.transcript ?? '').trim(), true)
        break
      case 'response.audio_transcript.delta':
        transcript.upsert(m.item_id, 'buyer', m.delta ?? '', false, true)
        break
      case 'response.audio_transcript.done':
        transcript.upsert(m.item_id, 'buyer', (m.transcript ?? '').trim(), true)
        break
    }
  }

  const offer = await pc.createOffer()
  await pc.setLocalDescription(offer)
  await new Promise<void>((resolve) => {
    if (pc.iceGatheringState === 'complete') return resolve()
    pc.onicegatheringstatechange = () => pc.iceGatheringState === 'complete' && resolve()
    setTimeout(resolve, 3000)
  })

  let connected
  try {
    connected = await Api.connect(sessionId, pc.localDescription!.sdp)
  } catch (err) {
    pc.close()
    audioEl.remove()
    await ctx.close()
    throw err
  }
  // The server's turn clock starts when it opened the socket; estimate that moment on
  // this clock so evidence timestamps map onto the recording (report seek).
  serverOpenAt = performance.now() - connected.connect_ms
  await pc.setRemoteDescription({ type: 'answer', sdp: connected.sdp_answer! })

  // "We can't hear you" detection (DESIGN §4).
  const buf = new Float32Array(micAnalyser.fftSize)
  let silentSince = performance.now()
  const meter = window.setInterval(() => {
    const level = rms(micAnalyser, buf)
    if (level > SILENT_RMS) {
      silentSince = performance.now()
      cb.onBanner(null)
    } else if (performance.now() - silentSince > SILENT_WARN_MS * 3) {
      cb.onBanner("We can't hear you — check your microphone.")
    }
  }, 250)

  let ended = false
  return {
    mode: 'webrtc',
    capSeconds: connected.cap_seconds,
    end: async (reason = 'rep_ended') => {
      if (ended) return null
      ended = true
      cb.onState('ending')
      window.clearInterval(meter)
      const rec = recorder as MediaRecorder | null
      if (rec && rec.state !== 'inactive') {
        await new Promise<void>((resolve) => {
          rec.addEventListener('stop', () => resolve(), { once: true })
          rec.stop()
        })
      }
      // Don't make the rep wait on the last chunk: /end goes now, uploads finish behind it
      // while scoring runs (the report polls and picks the recording up when it lands).
      pc.close()
      audioEl.remove()
      await ctx.close().catch(() => undefined)
      const { responses, ...tokens } = usage
      const res = await Api.end(sessionId, {
        reason,
        recorder_offset_ms: recorderOffsetMs,
        usage: responses ? { ...tokens, responses } : null,
        turn_starts: turnStarts,
      })
      cb.onState('ended')
      void uploads.then(() => uploadFailures && console.warn(`[audio] ${uploadFailures} chunk(s) failed`))
      return res.report_id ?? null
    },
  }
}

export async function startStubCall(sessionId: string, cb: CallCallbacks): Promise<ActiveCall> {
  cb.onState('connecting')
  const connected = await Api.connect(sessionId, null)
  cb.onState('live')
  let stopped = false
  const poll = async () => {
    while (!stopped) {
      const turns = await Api.transcript(sessionId).catch(() => [])
      cb.onTurns(turns.map((t) => ({ id: String(t.idx), speaker: t.speaker, text: t.text, final: true })))
      await new Promise((r) => setTimeout(r, 400))
    }
  }
  void poll()
  return {
    mode: 'stub',
    capSeconds: connected.cap_seconds,
    end: async (reason = 'rep_ended') => {
      stopped = true
      cb.onState('ending')
      const res = await Api.end(sessionId, { reason })
      cb.onState('ended')
      return res.report_id ?? null
    },
  }
}
