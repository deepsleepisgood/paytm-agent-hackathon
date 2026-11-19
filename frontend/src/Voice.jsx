import React, { useEffect, useRef, useState } from 'react'

const AGENTS = ['intelligence', 'risk', 'resolution', 'ledger']
const AGENT_NAMES = ['Intelligence', 'Risk', 'Resolution', 'Ledger']
const BAR_K = [0.35, 0.62, 0.88, 1, 0.88, 0.62, 0.35]
const CONFIRM_RE = /(haan|han|yes|ok|okay|theek|thik|bhej|kar do|हाँ|हां|ठीक)/i

const SpeakerIcon = ({ on }) => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" />
    {on ? <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11" /> : <path d="M16 9.5l5 5M21 9.5l-5 5" />}
  </svg>
)

export default function Voice({ m, chat, busy, run, reveal, speak, setSpeak, mode, prompts, nudge, onText, onAudio, onPreset, onConfirm, onMenu, onKhata, onAttach }) {
  const [phase, setPhase] = useState('idle') // idle | listening | speaking (thinking comes from `busy`)
  const [live, setLive] = useState('')
  const [spoken, setSpoken] = useState(0)
  const [note, setNote] = useState('')
  const orb = useRef(null)
  const rec = useRef({})
  const sim = useRef(null)
  const seen = useRef(chat.length)
  const speakTimer = useRef(null)
  const safety = useRef(null)
  const latest = useRef({})

  const setLevel = (v) => orb.current && orb.current.style.setProperty('--lvl', Math.max(0, Math.min(1, v)).toFixed(3))
  const last = chat[chat.length - 1]
  const lastMe = [...chat].reverse().find((c) => c.who === 'me')
  const reply = last && last.who === 'ai' && chat.length > 1 ? last : null
  const words = reply ? reply.text.split(/\s+/) : []
  const state = busy ? 'thinking' : phase
  const agentsDone = run ? run.steps.filter((s, i) => AGENTS.includes(s.key) && i < reveal).length : 0

  /* ---------- speaking the reply (TTS or backend audio), with karaoke highlight ---------- */
  const stopSpeaking = () => {
    clearInterval(speakTimer.current); clearTimeout(safety.current)
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    if (rec.current.audioEl) { rec.current.audioEl.pause(); rec.current.audioEl = null }
  }
  useEffect(() => {
    if (chat.length === seen.current) return
    seen.current = chat.length
    const msg = chat[chat.length - 1]
    if (!msg || msg.who !== 'ai') return
    const ws = msg.text.split(/\s+/)
    if (!speak) { setSpoken(ws.length); setPhase('idle'); return }
    stopSpeaking()
    setSpoken(0); setPhase('speaking')
    const done = () => { clearInterval(speakTimer.current); clearTimeout(safety.current); setSpoken(ws.length); setPhase('idle'); setLevel(0) }
    // Safety net: some browsers never fire onend (no Hindi voice installed), so never get stuck in 'speaking'.
    safety.current = setTimeout(done, ws.length * 450 + 3000)
    const wobble = () => { let t = 0; speakTimer.current = setInterval(() => { t += 0.35; setLevel(0.35 + 0.3 * Math.abs(Math.sin(t)) + 0.15 * Math.random()) }, 90) }
    let used = false
    if (msg.audio) {
      try {
        const a = new Audio('data:audio/wav;base64,' + msg.audio); rec.current.audioEl = a; used = true
        a.onended = done; a.onerror = done; a.play().catch(done)
        wobble()
        const per = 330; let i = 0; const kt = setInterval(() => { i += 1; setSpoken(i); if (i >= ws.length) clearInterval(kt) }, per)
      } catch { used = false }
    }
    if (!used && 'speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(msg.text); u.lang = 'hi-IN'; u.rate = 1
      const starts = []; let pos = 0; ws.forEach((w) => { starts.push(pos); pos += w.length + 1 })
      u.onboundary = (e) => { let idx = 0; for (let k = 0; k < starts.length; k++) if (starts[k] <= e.charIndex) idx = k; setSpoken(idx + 1) }
      u.onend = done; u.onerror = done
      wobble()
      window.speechSynthesis.speak(u)
      used = true
    }
    if (!used) { // no TTS available: simulate timing
      wobble(); let i = 0
      const kt = setInterval(() => { i += 1; setSpoken(i); if (i >= ws.length) { clearInterval(kt); done() } }, 320)
    }
  }, [chat.length])
  useEffect(() => () => { stopSpeaking(); cleanup() }, [])

  /* ---------- listening: mic level, live captions, silence detection ---------- */
  const cleanup = () => {
    const r = rec.current
    cancelAnimationFrame(r.raf); clearInterval(sim.current)
    if (r.stream) r.stream.getTracks().forEach((t) => t.stop())
    if (r.ctx) { try { r.ctx.close() } catch { /* ignore */ } }
    if (r.sr) { try { r.sr.onend = null; r.sr.stop() } catch { /* ignore */ } }
    r.stream = r.ctx = r.sr = null
    setLevel(0)
  }
  const route = (blob) => {
    const r = rec.current
    setPhase('idle')
    const text = (r.final || '').trim()
    const X = latest.current
    if (text) {
      setLive('')
      if (X.pending && CONFIRM_RE.test(text)) return X.onConfirm(X.reply, X.chat.length - 1)
      return X.onText(text)
    }
    if (blob && blob.size > 1500 && r.heard && X.mode === 'live') { setLive(''); return X.onAudio(blob) }
    setNote(r.heard ? 'आवाज़ समझ नहीं आई। नीचे से कोई सवाल चुन लीजिए।' : 'कुछ सुनाई नहीं दिया। माइक दबाकर फिर से बोलिए।')
  }
  const finish = () => {
    const r = rec.current
    if (r.done) return
    r.done = true
    const mr = r.mr
    cleanup()
    if (mr && mr.state !== 'inactive') {
      mr.onstop = () => route(new Blob(r.chunks, { type: mr.mimeType || 'audio/webm' }))
      try { mr.stop() } catch { route(null) }
    } else route(null)
    r.mr = null
  }
  const startListening = async () => {
    if (busy) return
    if (phase === 'listening') return finish()
    stopSpeaking()
    const r = rec.current
    r.done = false; r.final = ''; r.heard = false; r.chunks = []
    setNote(''); setLive(''); setPhase('listening')
    let stream = null
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) } catch { stream = null }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (stream) {
      const AC = window.AudioContext || window.webkitAudioContext
      const ctx = new AC(); const src = ctx.createMediaStreamSource(stream); const an = ctx.createAnalyser(); an.fftSize = 512; src.connect(an)
      const buf = new Uint8Array(an.fftSize); let quietSince = performance.now(); const t0 = performance.now()
      const tick = () => {
        an.getByteTimeDomainData(buf)
        let s = 0; for (const v of buf) { const d = (v - 128) / 128; s += d * d }
        const lvl = Math.min(1, Math.sqrt(s / buf.length) * 5)
        setLevel(lvl)
        const now = performance.now()
        if (lvl > 0.12) { r.heard = true; quietSince = now }
        if ((r.heard && now - quietSince > 1600) || now - t0 > 12000) return finish()
        r.raf = requestAnimationFrame(tick)
      }
      r.raf = requestAnimationFrame(tick)
      r.stream = stream; r.ctx = ctx
      if (window.MediaRecorder) { try { const mr = new MediaRecorder(stream); mr.ondataavailable = (e) => e.data.size && r.chunks.push(e.data); mr.start(); r.mr = mr } catch { /* no recorder */ } }
    } else {
      let t = 0; sim.current = setInterval(() => { t += 0.4; setLevel(0.25 + 0.2 * Math.abs(Math.sin(t))) }, 90)
    }
    if (SR) {
      try {
        const sr = new SR(); sr.lang = 'hi-IN'; sr.interimResults = true; sr.continuous = false
        sr.onresult = (e) => { let t = ''; for (const res of e.results) t += res[0].transcript; r.final = t; r.heard = true; setLive(t) }
        sr.onerror = () => {}
        sr.onend = () => finish()
        sr.start(); r.sr = sr
      } catch { /* ignore */ }
    }
    if (!stream && !SR) { cleanup(); r.done = true; setPhase('idle'); setNote('यहाँ माइक नहीं चल रहा। नीचे से कोई सवाल चुन लीजिए।') }
  }

  /* ---------- "say it for me": tapping a prompt animates speaking, then runs it ---------- */
  const sayPrompt = (p) => {
    if (busy || phase === 'listening') return
    stopSpeaking(); setNote(''); setLive(''); setPhase('listening')
    const ws = p.say.split(/\s+/); let i = 0; let t = 0
    sim.current = setInterval(() => { t += 0.5; setLevel(0.3 + 0.35 * Math.abs(Math.sin(t)) + 0.15 * Math.random()) }, 80)
    const typer = setInterval(() => {
      i += 1; setLive(ws.slice(0, i).join(' '))
      if (i >= ws.length) { clearInterval(typer); clearInterval(sim.current); setTimeout(() => { setPhase('idle'); setLive(''); setLevel(0); onPreset(p.id) }, 380) }
    }, 120)
  }

  // Voice sign-off: when a confirm button is pending, saying "haan" works too.
  const pending = reply && reply.confirm && !reply.done
  latest.current = { pending, reply, chat, mode, onText, onAudio, onConfirm }

  const cls = `voice ${state} ${speak ? '' : 'muted'}`
  return (
    <div className={cls}>
      <div className="aurora" /><div className="aurora a2" />
      <div className="v-top">
        <span className="v-who"><i className="live-dot" />{m.profile.name}</span>
        <button className="v-mute" onClick={() => { if (speak) stopSpeaking(); setSpeak(!speak) }} aria-label={speak ? 'Mute voice replies' : 'Unmute voice replies'}><SpeakerIcon on={speak} /></button>
      </div>

      <div className="orb-stage">
        <div ref={orb} className={`orb-wrap ${state}`} onClick={startListening} role="button" aria-label="माइक दबाकर बोलिए">
          <span className="ring r1" /><span className="ring r2" /><span className="ring r3" />
          <span className="sweep" />
          {Array.from({ length: 10 }).map((_, i) => <span key={i} className="pt" style={{ '--i': i }} />)}
          <div className="orb">
            <div className="shine" />
            <div className="vbars">{BAR_K.map((k, i) => <i key={i} style={{ '--k': k, '--d': `${(i % 4) * 0.12}s` }} />)}</div>
          </div>
        </div>
        <div className="state-lbl">{state === 'listening' ? 'सुन रहा हूँ…' : state === 'thinking' ? 'सोच रहा हूँ…' : state === 'speaking' ? 'बता रहा हूँ' : 'माइक दबाकर बोलिए'}</div>
        {state === 'thinking' && (
          <div className="agent-dots">{AGENT_NAMES.map((n, i) => <span key={n} className={i < agentsDone ? 'on' : ''}><i />{n}</span>)}</div>
        )}
      </div>

      <div className="v-cap">
        {state === 'listening' && <div className="cap live">{live || <span className="ph">बोलिए…</span>}</div>}
        {state === 'thinking' && lastMe && <div className="cap me">“{lastMe.text}”</div>}
        {(state === 'speaking' || state === 'idle') && lastMe && reply && <div className="cap me small">“{lastMe.text}”</div>}
        {(state === 'speaking' || state === 'idle') && reply && (
          <div className={`cap reply ${reply.tone || ''}`}>
            {words.map((w, i) => <span key={i} className={i < spoken ? 'on' : ''}>{w} </span>)}
          </div>
        )}
        {state === 'idle' && !reply && !note && (
          <div className="cap intro">
            {nudge ? (
              <button className="nudge" onClick={() => sayPrompt(nudge)}>
                <em>आज का ज़रूरी काम</em>
                <b>{nudge.title}</b>
                <span>{nudge.text}</span>
                <u>दबाइए →</u>
              </button>
            ) : (<>हिंदी या English में पूछिए</>)}
          </div>
        )}
        {note && state === 'idle' && <div className="cap note">{note}</div>}
        {pending && (
          <div className="sign">
            <button className="yes" onClick={() => onConfirm(reply, chat.length - 1)} disabled={busy}>{reply.confirm.label}</button>
            <span>या बोलिए “हाँ”</span>
          </div>
        )}
      </div>

      <div className={`v-prompts ${state === 'idle' ? '' : 'dim'}`}>
        <div className="vp-h">या नीचे से चुनिए</div>
        <div className="vp-row">
          {prompts.map((p) => (
            <button key={p.id} className="vp" disabled={busy || !p.ok} onClick={() => sayPrompt(p)}>
              <b>{p.hi}</b><span>बोलकर पूछें</span>
            </button>
          ))}
        </div>
        <div className="vp-links">
          <button onClick={onMenu}>सारी मदद</button>
          <button onClick={onKhata}>खाता</button>
          <button onClick={onAttach}>फ़ोटो भेजें</button>
        </div>
      </div>
    </div>
  )
}
