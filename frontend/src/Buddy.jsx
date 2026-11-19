import React, { useEffect, useRef, useState } from 'react'
import { AIMark } from './icons.jsx'
import Voice from './Voice.jsx'
import { SCENARIOS, liveOk } from './engine.js'
import { inr } from './data.js'
import Khata from './Khata.jsx'

// Every scenario, grouped for the "Madad menu" sheet.
const GROUPS = [
  { id: 'payout', label: 'Payout', items: [
    { id: 'settle', t: 'Paisa kahan kata?', s: 'Why is my settlement lower?' },
    { id: 'hold', t: 'Settlement hold', s: 'Bank / KYC hold on my money' },
    { id: 'sbrent', t: 'Soundbox rent kat raha', s: 'Charged after returning device' } ] },
  { id: 'pay', label: 'Payments', items: [
    { id: 'utr', t: 'UTR pending', s: 'Is this payment real?' },
    { id: 'dup', t: 'Duplicate payment', s: 'Charged twice for one order' },
    { id: 'fake', t: 'Fake screenshot', s: 'Catch a tampered UPI proof' },
    { id: 'refund', t: 'Refund karna hai', s: 'Auto up to ₹5,000, else human' } ] },
  { id: 'loan', label: 'Loan', items: [
    { id: 'edi', t: 'Loan EDI fail', s: 'Mandate failed, fix it' },
    { id: 'noc', t: 'Loan NOC', s: 'Paid negotiated settlement' },
    { id: 'growth', t: 'Business badhao', s: 'Ideas from my 6-month data' } ] },
  { id: 'pro', label: 'Alerts', items: [
    { id: 'shield_cb', t: 'Chargeback incoming', s: 'AI pulls PoD, you sign off' },
    { id: 'shield_edi', t: 'Cashflow gap', s: 'AI offers a 2-day EDI pause' } ] },
  { id: 'help', label: 'Help', items: [
    { id: 'cb', t: 'Chargeback proof', s: 'Send delivery proof, free the hold' },
    { id: 'bank', t: 'Bank account update', s: 'Change settlement account' },
    { id: 'soundbox', t: 'Soundbox kharab', s: 'Hardware issue, human ticket' } ] },
]

// The four big starting suggestions on the home state.
const SUGGEST = {
  settle: ['Paisa kahan kata?', 'Settlement ka hisaab samjhein'],
  utr: ['UTR check karo', 'Payment asli hai ya fake?'],
  cb: ['Chargeback proof', 'Delivery proof bhejein, hold hatayein'],
  hold: ['Settlement hold', 'Bank / KYC hold ka reason jaanein'],
  edi: ['Loan EDI problem', 'Mandate fail? Hum theek karte hain'],
}

const SpeakerIcon = ({ on }) => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" />
    {on ? <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11" /> : <path d="M16 9.5l5 5M21 9.5l-5 5" />}
  </svg>
)
const PlusIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
)
const MicIcon = () => (
  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
)

function Insights({ m, always }) {
  const [open, setOpen] = useState(!!always)
  const i = m.insights
  const ms = i.monthly_sales
  const max = Math.max(...ms), min = Math.min(...ms)
  const pts = ms.map((v, k) => `${(k / (ms.length - 1)) * 100},${34 - ((v - min) / (max - min || 1)) * 28}`).join(' ')
  const pct = Math.round(((ms[ms.length - 1] - ms[0]) / ms[0]) * 100)
  const wmax = Math.max(...i.weekday_avg_sales)
  const top = [...i.weekday_avg_sales].sort((a, b) => b - a).slice(0, 2)
  const h = i.cashflow_health
  if (!open) {
    return (
      <button className="ins-min" onClick={() => setOpen(true)}>
        <span><b>Aapka business</b></span>
        <span className={`trend ${pct >= 0 ? 'up' : 'dn'}`}>{pct >= 0 ? '▲' : '▼'} {Math.abs(pct)}%</span>
        <span className="chip-i">Cash health {h.score} · {h.label}</span>
        <span className="r-go">⌄</span>
      </button>
    )
  }
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
      {!always && <button className="ins-close" onClick={() => setOpen(false)}>Hide ⌃</button>}
    </div>
  )
}

export default function Buddy({ m, L, chat, busy, mode, run, reveal, onPreset, onText, onAudio, onUpload, onConfirm, speak, setSpeak, onTheme }) {
  const [view, setView] = useState('voice') // 'voice' | 'menu' | 'khata'
  const [attach, setAttach] = useState(false)
  const podRef = useRef(null)
  const shotRef = useRef(null)


  const okFor = (id) => {
    const s = SCENARIOS.find((x) => x.id === id)
    return !!s && (!s.available || s.available(m)) && (mode !== 'live' || liveOk(s))
  }
  const promptIds = ['settle', 'utr', okFor('cb') ? 'cb' : 'hold', 'edi', 'dup', 'growth']
  const prompts = promptIds.map((id) => {
    const s = SCENARIOS.find((x) => x.id === id)
    return { id, t: SUGGEST[id] ? SUGGEST[id][0] : (GROUPS.flatMap((g) => g.items).find((it) => it.id === id) || {}).t, say: s.utterance(m), ok: okFor(id) }
  })
  const HI = { settle: 'पैसा कहाँ कटा?', utr: 'UTR जाँचें', cb: 'डिलीवरी प्रूफ भेजें', hold: 'सेटलमेंट होल्ड', edi: 'लोन EDI फेल', dup: 'दो बार पैसा कटा', growth: 'धंधा कैसे बढ़ाएँ' }
  prompts.forEach((p) => { p.hi = HI[p.id] || p.t })
  // Smart nudge: the single most urgent thing for this merchant today, from their own data.
  const cb = m.d.chargeback
  const edi = m.d.loan.edi
  const nudge = cb && cb.status === 'HELD'
    ? { id: 'shield_cb', title: `${cb.order} का ₹${cb.amount} रुका हुआ है`, text: 'डिलीवरी का सबूत भेजिए, पैसा 48 घंटे में छूट जाएगा।', say: SCENARIOS.find((s) => s.id === 'cb')?.utterance(m) || '' , run: okFor('cb') ? 'cb' : 'settle' }
    : { id: 'settle', title: 'आज का हिसाब देखें', text: 'सेटलमेंट में कितना कटा, एक बटन में जानिए।', say: '', run: 'settle' }
  const nudgeP = { ...nudge, id: nudge.run, say: SCENARIOS.find((s) => s.id === nudge.run).utterance(m) }
  const run1 = (id) => { setView('voice'); onPreset(id) }

  const Back = ({ title }) => (
    <div className="pg-nav">
      <button className="pg-back" onClick={() => setView('voice')} aria-label="Back to Assistant">
        <svg width="12" height="20" viewBox="0 0 12 20" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2L2 10l8 8" /></svg>
        <span>Assistant</span>
      </button>
      <b>{title}</b>
      <span className="pg-sp" />
    </div>
  )

  if (view === 'menu') {
    return (
      <div className="screen buddy pg">
        <Back title="Madad menu" />
        <div className="pg-body">
          <Insights m={m} always />
          {GROUPS.map((g) => (
            <div key={g.id} className="pg-sec">
              <div className="ios-cap">{g.label.toUpperCase()}</div>
              <div className="rows">
                {g.items.map((it) => {
                  const ok = okFor(it.id)
                  const sc = SCENARIOS.find((x) => x.id === it.id)
                  const why = mode === 'live' && !liveOk(sc) ? 'Local demo only (not in contract yet)' : 'Not applicable for this merchant'
                  return (
                    <button key={it.id} className="row-btn" disabled={busy || !ok} onClick={() => run1(it.id)}>
                      <span className="r-t"><b>{it.t}</b><em>{ok ? it.s : why}</em></span>
                      <span className="r-go">›</span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (view === 'khata') {
    return (
      <div className="screen buddy pg">
        <Back title="Khata & Tally" />
        <Khata m={m} L={L} page />
      </div>
    )
  }

  return (
    <div className="screen buddy voice-screen">
      <Voice m={m} chat={chat} busy={busy} run={run} reveal={reveal} speak={speak} setSpeak={setSpeak} mode={mode} prompts={prompts} nudge={nudgeP}
        onText={onText} onAudio={onAudio} onPreset={onPreset} onConfirm={onConfirm}
        onMenu={() => setView('menu')} onKhata={() => setView('khata')} onAttach={(k) => (k === 'pod' ? podRef.current.click() : k === 'shot' ? shotRef.current.click() : setAttach(true))} />
      {attach && (
        <div className="attach-sheet" onClick={() => setAttach(false)}>
          <div className="as-card" onClick={(e) => e.stopPropagation()}>
            <div className="as-h">क्या भेजना है?</div>
            <button className="as-opt" disabled={busy} onClick={() => { setAttach(false); podRef.current.click() }}>
              <b>डिलीवरी का सबूत</b><span>ग्राहक को सामान मिल गया — रसीद या फ़ोटो</span>
            </button>
            <button className="as-opt" disabled={busy} onClick={() => { setAttach(false); shotRef.current.click() }}>
              <b>UPI पेमेंट का स्क्रीनशॉट</b><span>ग्राहक ने पेमेंट दिखाया — असली है या नकली जाँचें</span>
            </button>
            <div className="as-note">कैमरा से फ़ोटो लें या गैलरी से चुनें</div>
            <button className="as-cancel" onClick={() => setAttach(false)}>रद्द करें</button>
          </div>
        </div>
      )}
      <input ref={podRef} type="file" hidden accept="image/*,.pdf" onChange={(e) => { const f = e.target.files[0]; if (f) onUpload('pod', f); e.target.value = '' }} />
      <input ref={shotRef} type="file" hidden accept="image/*" onChange={(e) => { const f = e.target.files[0]; if (f) onUpload('shot', f); e.target.value = '' }} />
    </div>
  )
}
