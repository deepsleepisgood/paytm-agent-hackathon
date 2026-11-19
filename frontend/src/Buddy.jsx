import React, { useEffect, useRef, useState } from 'react'
import { I, PaytmLogo } from './icons.jsx'
import { SCENARIOS } from './engine.js'
import { inr } from './data.js'
import Khata from './Khata.jsx'

const GROUPS = [
  { id: 'payout', label: 'Payout', items: [
    { id: 'settle', ic: '💰', t: 'Paisa kahan kata?', s: 'Why is my settlement lower?' },
    { id: 'hold', ic: '🔒', t: 'Settlement hold', s: 'Bank / KYC hold on my money' },
    { id: 'sbrent', ic: '🔊', t: 'Soundbox rent kat raha', s: 'Charged after returning device' } ] },
  { id: 'pay', label: 'Payments', items: [
    { id: 'utr', ic: '🔎', t: 'UTR pending', s: 'Is this payment real?' },
    { id: 'fake', ic: '🚫', t: 'Fake screenshot', s: 'Catch a tampered UPI proof' },
    { id: 'refund', ic: '↩️', t: 'Refund karna hai', s: 'Auto up to ₹5,000, else human' } ] },
  { id: 'loan', label: 'Loan & growth', items: [
    { id: 'edi', ic: '🏦', t: 'Loan EDI fail', s: 'Mandate failed, fix it' },
    { id: 'noc', ic: '📄', t: 'Loan NOC', s: 'Paid negotiated settlement' },
    { id: 'growth', ic: '📈', t: 'Business badhao', s: 'Ideas from my 6-month data' } ] },
  { id: 'help', label: 'Disputes & help', items: [
    { id: 'cb', ic: '⚖️', t: 'Chargeback proof', s: 'Send delivery proof, free the hold' },
    { id: 'bank', ic: '🏛️', t: 'Bank account update', s: 'Change settlement account' },
    { id: 'soundbox', ic: '🛠️', t: 'Soundbox kharab', s: 'Hardware issue → human ticket' } ] },
]

function Insights({ m }) {
  const i = m.insights
  const ms = i.monthly_sales
  const max = Math.max(...ms), min = Math.min(...ms)
  const pts = ms.map((v, k) => `${(k / (ms.length - 1)) * 100},${34 - ((v - min) / (max - min || 1)) * 28}`).join(' ')
  const pct = Math.round(((ms[ms.length - 1] - ms[0]) / ms[0]) * 100)
  const wmax = Math.max(...i.weekday_avg_sales)
  const top = [...i.weekday_avg_sales].sort((a, b) => b - a).slice(0, 2)
  const h = i.cashflow_health
  return (
    <div className="ins">
      <div className="ins-h"><b>Aapka business, ek nazar mein</b><span className="muted xs">{i.period}</span></div>
      <div className="ins-grid">
        <div>
          <div className="muted xs">Sales trend</div>
          <svg viewBox="0 0 100 38" className="spark"><polyline points={pts} fill="none" stroke="#00baf2" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" /></svg>
          <div className={`trend ${pct >= 0 ? 'up' : 'dn'}`}>{pct >= 0 ? '▲' : '▼'} {Math.abs(pct)}%</div>
        </div>
        <div>
          <div className="muted xs">Busiest days</div>
          <div className="wk">
            {i.weekday_avg_sales.map((v, k) => (
              <span key={k} title={`${i.weekdays[k]} ${inr(v)}`}><i className={top.includes(v) ? 'pk' : ''} style={{ height: 8 + (v / wmax) * 30 }} /><em>{i.weekdays[k][0]}</em></span>
            ))}
          </div>
        </div>
        <div className="gauge">
          <div className="muted xs">Cash health</div>
          <div className="ring" style={{ '--p': h.score }}><b>{h.score}</b></div>
          <div className="xs b">{h.label}</div>
        </div>
      </div>
      <div className="ins-note">{i.peak_note}</div>
    </div>
  )
}

export default function Buddy({ m, L, chat, busy, onPreset, onText, onUpload, speak, setSpeak }) {
  const [text, setText] = useState('')
  const [rec, setRec] = useState(false)
  const [micNote, setMicNote] = useState('')
  const [khata, setKhata] = useState(false)
  const [cat, setCat] = useState('payout')
  const end = useRef(null)
  const podRef = useRef(null)
  const shotRef = useRef(null)

  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [chat.length, busy])

  const send = () => { if (text.trim() && !busy) { onText(text.trim()); setText('') } }

  const mic = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) return setMicNote('Mic not supported here. Tap a quick scenario.')
    if (rec) return
    const r = new SR()
    r.lang = 'hi-IN'
    r.onstart = () => { setRec(true); setMicNote('Sun raha hoon…') }
    r.onerror = () => { setRec(false); setMicNote('Mic unavailable. Tap a quick scenario.') }
    r.onend = () => setRec(false)
    r.onresult = (e) => { const t = e.results[0][0].transcript; setMicNote(''); onText(t) }
    try { r.start() } catch { setRec(false) }
  }

  return (
    <div className="screen buddy">
      <div className="topbar tight">
        <PaytmLogo size={20} />
        <div className="tb-r">
          <button className={`spk ${speak ? 'on' : ''}`} onClick={() => setSpeak(!speak)} title="Hindi voice reply">🔊</button>
        </div>
      </div>
      <div className="b-title"><span className="ai-dot"><I.Spark size={14} /></span><div><b>Merchant AI Buddy</b><div className="muted xs">{m.profile.name} · {m.mid}</div></div></div>

      <div className="b-scroll">
        <Insights m={m} />

        <div className="pk-h"><b>Kya madad chahiye?</b><span className="muted xs">Tap one, watch the AI work →</span></div>
        <div className="cats">
          {GROUPS.map((g) => <button key={g.id} className={cat === g.id ? 'on' : ''} onClick={() => setCat(g.id)}>{g.label}</button>)}
        </div>
        <div className="rows">
          {GROUPS.find((g) => g.id === cat).items.map((it) => {
            const s = SCENARIOS.find((x) => x.id === it.id)
            const ok = !s.available || s.available(m)
            return (
              <button key={it.id} className="row-btn" disabled={busy || !ok} onClick={() => onPreset(it.id)} title={ok ? s.utterance(m) : 'No active chargeback for this merchant'}>
                <span className="r-ic">{it.ic}</span>
                <span className="r-t"><b>{it.t}</b><em>{ok ? it.s : 'Not applicable for this merchant'}</em></span>
                <span className="r-go">›</span>
              </button>
            )
          })}
        </div>

        <button className="khata-btn" onClick={() => setKhata(true)}>📊 Khata & Tally Export <span>›</span></button>

        <div className="chat">
          {chat.map((c, k) => (
            <div key={k} className={`msg ${c.who}`}>
              {c.who === 'ai' && <span className="ai-dot sm"><I.Spark size={11} /></span>}
              <div className={`bubble ${c.tone || ''}`}>{c.text}</div>
            </div>
          ))}
          {busy && <div className="msg ai"><span className="ai-dot sm"><I.Spark size={11} /></span><div className="bubble typing"><i /><i /><i /></div></div>}
          <div ref={end} />
        </div>
      </div>

      {khata && <Khata m={m} L={L} onClose={() => setKhata(false)} />}

      <div className="composer">
        <div className="upl">
          <button disabled={busy} onClick={() => podRef.current.click()}>📄 PoD upload</button>
          <button disabled={busy} onClick={() => shotRef.current.click()}>📱 UPI screenshot</button>
          <input ref={podRef} type="file" hidden accept="image/*,.pdf" onChange={(e) => { const f = e.target.files[0]; if (f) onUpload('pod', f.name); e.target.value = '' }} />
          <input ref={shotRef} type="file" hidden accept="image/*" onChange={(e) => { const f = e.target.files[0]; if (f) onUpload('shot', f.name); e.target.value = '' }} />
        </div>
        {micNote && <div className="mic-note">{micNote}</div>}
        <div className="inp">
          <button className={`mic ${rec ? 'rec' : ''}`} onClick={mic} aria-label="Voice">🎙️</button>
          <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} placeholder="Hindi / Hinglish mein poochiye…" />
          <button className="send" onClick={send} disabled={busy || !text.trim()}>➤</button>
        </div>
      </div>
    </div>
  )
}
