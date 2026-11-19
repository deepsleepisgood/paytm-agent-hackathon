import React, { useEffect, useRef, useState } from 'react'
import { I, PaytmLogo, AIMark, MerchantLogo } from './icons.jsx'
import { inr } from './data.js'
import { MERCHANTS, DEFAULT_MERCHANT } from './merchants.js'
import { SCENARIOS, runScenario, routeText, initLedger, applyEffects, liveOk, sayText, CONFIRM_LABEL } from './engine.js'
import Buddy from './Buddy.jsx'
import { loadLang, saveLang, t as tr } from './i18n.js'
import Center from './Center.jsx'
import Right from './Right.jsx'
import { checkServices, getLedger, resetLive, getStrategyMemory, transcribe, getPaymentWatch } from './api.js'
import { callLive, responseToRun, overlayLedger, overlayStrategy, overlaySupabase } from './live.js'
import { useLedgerRealtime } from './useLedgerRealtime.js'

const TABS = [
  { id: 'home', label: 'Home', icon: I.Home },
  { id: 'settlements', label: 'Settlements', icon: I.Bank },
  { id: 'buddy', label: 'AI Buddy', icon: I.Spark, center: true },
  { id: 'loans', label: 'Loan', icon: I.Loan },
  { id: 'account', label: 'Account', icon: I.User },
]
const TOPS = TABS.map((t) => t.id)

const clock = () => new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }).replace(/\s?(AM|PM)/i, '')

// iOS-style status bar: live time, signal bars, Wi-Fi and battery (all drawn as SVG, no "5G" text).
function StatusBar() {
  const [t, setT] = useState(clock())
  useEffect(() => { const i = setInterval(() => setT(clock()), 15000); return () => clearInterval(i) }, [])
  return (
    <div className="statusbar" aria-hidden="true">
      <span className="sb-time">{t}</span>
      <span className="sb-right">
        <svg width="19" height="12" viewBox="0 0 19 12" fill="currentColor"><rect x="0" y="8" width="3.2" height="4" rx="1" /><rect x="5" y="5.5" width="3.2" height="6.5" rx="1" /><rect x="10" y="3" width="3.2" height="9" rx="1" /><rect x="15" y="0" width="3.2" height="12" rx="1" /></svg>
        <svg width="17" height="13" viewBox="0 0 17 13" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><path d="M1.3 4.4a10.4 10.4 0 0 1 14.4 0" /><path d="M3.8 7a6.9 6.9 0 0 1 9.4 0" /><path d="M6.3 9.4a3.4 3.4 0 0 1 4.4 0" /><circle cx="8.5" cy="11.4" r=".9" fill="currentColor" stroke="none" /></svg>
        <svg width="27" height="13" viewBox="0 0 27 13" fill="none"><rect x=".5" y=".5" width="22.5" height="12" rx="3.8" stroke="currentColor" strokeOpacity=".4" /><rect x="2" y="2" width="17" height="9" rx="2.4" fill="currentColor" /><path d="M24.6 4.4v4.2c.9-.3 1.6-1.2 1.6-2.1s-.7-1.8-1.6-2.1z" fill="currentColor" fillOpacity=".45" /></svg>
      </span>
    </div>
  )
}

function Badge({ status }) {
  const cls = { SUCCESS: 'ok', PENDING: 'warn', REFUNDED: 'info', HELD: 'warn', PROCESSED: 'ok' }[status] || 'info'
  return <span className={`badge ${cls}`}>{status === 'SUCCESS' ? 'Success' : status[0] + status.slice(1).toLowerCase()}</span>
}

/* ---------------- Home ---------------- */
function Home({ d, go }) {
  const [hide, setHide] = useState(false)
  const paid = d.transactions.filter((t) => t.status !== 'REFUNDED')
  const refunds = d.transactions.filter((t) => t.status === 'REFUNDED')
  const sum = (l) => l.reduce((s, t) => s + t.amount, 0)
  const m = (v) => (hide ? '₹ ••••' : inr(v))
  const actions = [
    { l: 'Show QR', i: I.QR, to: 'qr' },
    { l: 'Settlements', i: I.Settle, to: 'settlements' },
    { l: 'Payment\nHistory', i: I.History, to: 'history' },
    { l: 'Soundbox', i: I.Speaker, to: 'soundbox' },
    { l: 'Refunds', i: I.Refund, to: 'refunds' },
    { l: 'Reports', i: I.Report, to: 'settlements' },
    { l: 'Business\nLoan', i: I.Loan, to: 'loans' },
    { l: 'Offers', i: I.Offer, to: 'offers' },
  ]
  return (
    <div className="screen">
      <div className="topbar">
        <PaytmLogo size={22} />
        <div className="tb-r">
          <button className="ai-badge" onClick={() => go('buddy')} aria-label="AI Teammate"><I.Spark size={14} /><b>AI</b></button>
          <span className="dotwrap"><I.Bell size={22} /><em /></span>
        </div>
      </div>
      <div className="greet">
        <MerchantLogo d={d} size={48} />
        <div><div className="m-name">{d.merchant}</div><div className="muted sm">Business Owner · {d.mid}</div></div>
      </div>

      <div className="promos">
        <div className="promo-card navy" onClick={() => go('settlements')}>
          <b>Get your money in one click!</b>
          <span>Try the Settle Now option</span>
          <em>Start Today ›</em>
        </div>
        <div className="promo-card blue" onClick={() => go('soundbox')}>
          <b>Grow your business with Paytm Soundbox</b>
          <em>Order now ›</em>
        </div>
      </div>

      <div className="sec-h">
        <b>Business overview</b>
        <span className="seg"><i className="on">Today</i></span>
        <button className="icon-btn" onClick={() => setHide(!hide)}><I.Eye size={18} /></button>
      </div>
      <div className="stats">
        <div className="stat s-blue" onClick={() => go('history')}>
          <span className="muted sm">Payments</span>
          <div className="sv">{m(sum(paid))} ›</div>
          <span className="muted xs">{paid.length} Payments</span>
        </div>
        <div className="stat s-mint" onClick={() => go('settlements')}>
          <span className="muted sm">Settlement</span>
          <div className="sv">{m(d.settlement.net)} ›</div>
          <span className="muted xs">Last settled {d.settlement.date}</span>
        </div>
        <div className="stat s-sand" onClick={() => go('refunds')}>
          <span className="muted sm">Refunds</span>
          <div className="sv">{m(sum(refunds))} ›</div>
          <span className="muted xs">{refunds.length} Payment</span>
        </div>
      </div>

      <div className="card settle-card" onClick={() => go('settlements')}>
        <div className="row between"><b>Latest Settlement</b><span className="muted sm">{d.settlement.date}</span></div>
        <div className="row between mt">
          <div><div className="muted sm">Gross</div><div className="v">{inr(d.settlement.gross)}</div></div>
          <div><div className="muted sm">Deductions</div><div className="v red">−{inr(d.settlement.variance)}</div></div>
          <div><div className="muted sm">Bank credit</div><div className="v green">{inr(d.settlement.net)}</div></div>
        </div>
        <div className="hint"><I.Alert size={16} /> {inr(d.settlement.variance)} less than expected? Tap to see why</div>
      </div>

      <div className="card grid">
        {actions.map((a) => (
          <button key={a.l} className="ga" onClick={() => go(a.to)}>
            <span className="ga-ic"><a.i size={24} /></span>
            <span className="ga-l">{a.l}</span>
          </button>
        ))}
      </div>

      <div className="loan-banner" onClick={() => go('loans')}>
        <div>
          <small>Business Loan</small>
          <b>Get up to ₹35 Lakh</b>
          <span>Collateral free · Instant · Low interest</span>
          <button className="cta sm">Apply Now</button>
        </div>
        <div className="loan-art"><I.Loan size={44} /></div>
      </div>

      <div className="card txn-list">
        <div className="row between"><b>Recent payments</b><button className="link" onClick={() => go('history')}>See all</button></div>
        {d.transactions.slice(0, 3).map((t) => <TxnRow key={t.utr} t={t} />)}
      </div>
    </div>
  )
}

function TxnRow({ t }) {
  const refund = t.status === 'REFUNDED'
  return (
    <div className="txn">
      <div className={`t-ic ${refund ? 'r' : ''}`}>{refund ? <I.Refund size={18} /> : <I.Down size={18} />}</div>
      <div className="t-mid">
        <div className="t-name">{t.name}</div>
        <div className="muted sm">{t.app} · UTR {t.utr} · {t.time}</div>
      </div>
      <div className="t-r">
        <div className={refund ? 'red b' : 'b'}>{refund ? '−' : '+'}{inr(t.amount)}</div>
        <Badge status={t.status} />
      </div>
    </div>
  )
}

/* ---------------- History ---------------- */
function History({ d, back }) {
  const [f, setF] = useState('ALL')
  const list = d.transactions.filter((t) => f === 'ALL' || t.status === f)
  return (
    <div className="screen">
      <Header title="Payment History" back={back} />
      <div className="chips">
        {['ALL', 'SUCCESS', 'PENDING', 'REFUNDED'].map((c) => (
          <button key={c} className={`chip ${f === c ? 'on' : ''}`} onClick={() => setF(c)}>{c === 'ALL' ? 'All' : c[0] + c.slice(1).toLowerCase()}</button>
        ))}
      </div>
      <div className="card txn-list">{list.map((t) => <TxnRow key={t.utr} t={t} />)}</div>
    </div>
  )
}

/* ---------------- Settlement ---------------- */
function Settlement({ d, back }) {
  const s = d.settlement
  return (
    <div className="screen">
      <Header title="Settlement Details" back={back} />
      <div className="card center-card">
        <div className="muted">Credited to bank · {s.date}</div>
        <div className="big green">{inr(s.net)}</div>
        <div className="pill ok"><I.Check size={14} /> Settled to HDFC ••4821</div>
      </div>
      <div className="card">
        <div className="row between line"><span>Gross collection</span><b>{inr(s.gross)}</b></div>
        {s.deductions.map((x) => (
          <div className="line" key={x.key}>
            <div className="row between"><span>{x.label}</span><b className="red">−{inr(x.amount)}</b></div>
            <div className="muted sm">{x.note}</div>
          </div>
        ))}
        <div className="row between line total"><b>Net bank credit</b><b className="green">{inr(s.net)}</b></div>
      </div>
      <div className="card info">
        <I.Spark size={18} />
        <span>Total deductions {inr(s.variance)}. Fees and GST can be claimed as ITC; chargeback hold releases after proof of delivery.</span>
      </div>
    </div>
  )
}

/* ---------------- Soundbox ---------------- */
function Soundbox({ back }) {
  return (
    <div className="screen">
      <Header title="Soundbox" back={back} />
      <div className="card center-card">
        <div className="sb-device"><I.Speaker size={56} /></div>
        <b>Paytm Soundbox 4G</b>
        <div className="muted sm">Device ID SB-88213 · Connected</div>
        <div className="pill ok mt">Battery 82%</div>
      </div>
      <div className="card">
        <div className="row between line"><span>Language</span><b>Hinglish</b></div>
        <div className="row between line"><span>Volume</span><b>High</b></div>
        <div className="row between line"><span>Monthly rental</span><b>{inr(149)}</b></div>
        <div className="row between line"><span>Last payment announced</span><b>{inr(3200)}</b></div>
      </div>
    </div>
  )
}

/* ---------------- Loans ---------------- */
function Loans({ d }) {
  const l = d.loan
  const pct = Math.round(((l.principal - l.balance) / l.principal) * 100)
  return (
    <div className="screen">
      <Header title="Business Loan" />
      <div className="card loan">
        <div className="muted">{l.lender ? `${l.lender} · outstanding balance` : 'Outstanding balance'}</div>
        <div className="big">{inr(l.balance)}</div>
        <div className="bar"><i style={{ width: pct + '%' }} /></div>
        <div className="muted sm">{pct}% repaid of {inr(l.principal)}</div>
      </div>
      <div className="card">
        <div className="row between line"><span>Daily EDI</span><b>{inr(l.edi)}/day</b></div>
        <div className="row between line"><span>Next deduction</span><b>{l.next}</b></div>
        <div className="row between line"><span>Deducted from</span><b>Bank account (eNACH)</b></div>
      </div>
      {l.history && (
        <div className="card">
          <b>Last 7 EDIs</b>
          <div className="edi-h">
            {l.history.map((h) => (
              <span key={h.date} className={`st ${h.status === 'SUCCESS' ? 'ok' : h.status.startsWith('BOUNCE') || h.status === 'FAILED' ? 'warn' : 'info'}`} title={h.status}>{h.date.slice(5)}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ---------------- Account ---------------- */
function Account({ d }) {
  const rows = [
    ['Business profile', d.merchant], ['Merchant ID', d.mid], ['Bank account', 'HDFC ••4821'],
    ['GST number', '07AABCS1429B1Z5'], ['Language', 'English'], ['Help & Support', ''],
  ]
  return (
    <div className="screen">
      <Header title="Account" />
      <div className="card center-card"><MerchantLogo d={d} size={84} /><b>{d.merchant}</b><div className="muted sm">{d.mid}</div></div>
      <div className="card">
        {rows.map(([a, b]) => (
          <div key={a} className="row between line"><span>{a}</span><span className="muted">{b} <I.Chev size={14} /></span></div>
        ))}
      </div>
    </div>
  )
}

/* ---------------- Simple extras ---------------- */
function QR({ back, d }) {
  const cells = Array.from({ length: 169 }, (_, i) => ((i * 7 + (i >> 3) * 3) % 5 < 2) || [0, 1, 2, 10, 11, 12].includes(i % 13) && [0, 1, 2, 10, 11, 12].includes(i / 13 | 0))
  return (
    <div className="screen">
      <Header title="Payment QR" back={back} />
      <div className="card center-card">
        <b>{d.merchant}</b>
        <div className="qr">{cells.map((c, i) => <i key={i} className={c ? 'on' : ''} />)}</div>
        <div className="muted sm">Scan with any UPI app to pay</div>
      </div>
    </div>
  )
}

function Refunds({ back, d }) {
  const r = d.transactions.filter((t) => t.status === 'REFUNDED')
  return (
    <div className="screen">
      <Header title="Refunds" back={back} />
      <div className="card txn-list">{r.map((t) => <TxnRow key={t.utr} t={t} />)}</div>
    </div>
  )
}

function Offers({ back }) {
  return (
    <div className="screen">
      <Header title="Offers" back={back} />
      {['Zero MDR on Bank UPI payments', 'Get a free Soundbox 4G on ₹50k monthly volume', 'Business loan up to ₹10L, instant approval'].map((o) => (
        <div className="card promo" key={o}><b>{o}</b></div>
      ))}
    </div>
  )
}

function Header({ title, back }) {
  return (
    <div className="hdr">
      {back ? <button className="icon-btn" onClick={back}><I.Back size={22} /></button> : <span style={{ width: 22 }} />}
      <b>{title}</b>
      <span style={{ width: 22 }} />
    </div>
  )
}

/* ---------------- Shell: 3-column command center ---------------- */
const STEP_MS = 700
const welcome = (m) => [{ who: 'ai', text: `Namaste ${m.profile.owner.split(' ')[0]} ji! Main ${m.profile.name} ka AI Buddy hoon. Settlement, UTR, chargeback, refund, loan EDI — kuch bhi poochiye.` }]

const LIVE_MERCHANT = 'sharma_electronics' // real backends only know PAYTM_MERCH_8821

export default function App() {
  const [mkey, setMkey] = useState(DEFAULT_MERCHANT)
  const m = MERCHANTS[mkey]
  const [tab, setTab] = useState('buddy')
  const [sub, setSub] = useState(null)
  const [svc, setSvc] = useState({ merchant: false, paytm: false })
  const [mode, setMode] = useState('local') // 'local' | 'live'
  const [ledger, setLedger] = useState(() => initLedger(m))
  const [chat, setChat] = useState(() => welcome(m))
  const [run, setRun] = useState(null)
  const [reveal, setReveal] = useState(0)
  const [busy, setBusy] = useState(false)
  const [speak, setSpeak] = useState(true)
  const [dark, setDark] = useState(false)
  const [lang, setLangState] = useState(loadLang)
  const setLang = (l) => { setLangState(l); saveLang(l) }
  const [queue, setQueue] = useState([])
  const timers = useRef([])
  const scroller = useRef(null)
  const modeRef = useRef(mode)
  const autoLive = useRef(false)
  modeRef.current = mode
  // Supabase Realtime (read-only anon key). Disabled without VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY.
  const sb = useLedgerRealtime()
  useEffect(() => {
    if (mode === 'live') setLedger((L) => overlaySupabase(L, sb))
  }, [mode, sb.status, sb.chargebacks, sb.loan])

  useEffect(() => { scroller.current?.scrollTo(0, 0) }, [tab, sub])
  // Poll which backends are reachable (8003 needed for live mode; 8002 optional — 8003 mocks Paytm if it is down).
  useEffect(() => {
    let off = false
    const poll = () => checkServices().then((s) => { if (!off) { setSvc(s); if (!s.merchant && modeRef.current === 'live') setMode('local') } })
    poll()
    const t = setInterval(poll, 6000)
    return () => { off = true; clearInterval(t) }
  }, [])

  // Live: the buddy keeps watching stuck payments it found; tell the merchant the moment one lands or goes back.
  const announced = useRef(new Set())
  useEffect(() => {
    if (mode !== 'live') return
    const poll = () => getPaymentWatch(lang).then((w) => {
      for (const x of w?.watching || []) {
        if (x.message && !announced.current.has(x.utr)) {
          announced.current.add(x.utr)
          setChat((c) => [...c, { who: 'ai', text: x.message, tone: x.outcome === 'ARRIVED' ? 'good' : undefined }])
        }
      }
    })
    const i = setInterval(poll, 15000)
    return () => clearInterval(i)
  }, [mode, lang])

  const clear = () => { timers.current.forEach(clearTimeout); timers.current = [] }
  useEffect(() => clear, [])

  const reset = (key = mkey, resetServices = false) => {
    clear()
    const nm = MERCHANTS[key]
    setLedger(initLedger(nm)); setChat(welcome(nm)); setRun(null); setReveal(0); setBusy(false); setTab('buddy'); setSub(null)
    // Realtime doesn't stream the reset's TRUNCATE, so re-read Supabase once the services are back to the start state.
    if (resetServices && modeRef.current === 'live') resetLive().then(() => sb.refetch())
  }
  const pickMerchant = (key) => {
    setMkey(key)
    if (mode === 'live' && key !== LIVE_MERCHANT) setMode('local')
    reset(key)
  }
  const switchMode = (next) => {
    if (next === 'live') {
      if (!svc.merchant) return
      setMode('live'); modeRef.current = 'live'
      setMkey(LIVE_MERCHANT); reset(LIVE_MERCHANT, true)
    } else { setMode('local'); modeRef.current = 'local'; reset(mkey) }
  }

  // First time the backend is reachable, start in Live mode on the contract merchant so the demo uses the real agents.
  useEffect(() => {
    if (svc.merchant && !autoLive.current && mkey === LIVE_MERCHANT) { autoLive.current = true; switchMode('live') }
  }, [svc.merchant])

  // Plays a run (local or live) step by step: reveals trace cards, applies ledger effects, posts the reply.
  const play = (r, gap) => {
    setTab('buddy'); setSub(null)
    setRun(r); setReveal(0); setBusy(true)
    r.steps.forEach((s, i) => {
      timers.current.push(setTimeout(() => {
        setReveal(i + 1)
        if (s.effects) setLedger((L) => applyEffects(L, s.effects))
        if (s.key === 'reply') {
          setChat((c) => [...c, { who: 'ai', text: s.reply, texts: s.replies, tone: s.tone, confirm: s.confirm && CONFIRM_LABEL[s.confirm.kind] ? { ...s.confirm, label: CONFIRM_LABEL[s.confirm.kind][lang] } : s.confirm, audio: r.audio }])
          setBusy(false)
          if (r.live) {
            getLedger(m.mid).then((led) => led && setLedger((L) => overlayLedger(L, led)))
            getStrategyMemory().then((sm) => sm && setLedger((L) => overlayStrategy(L, sm)))
          }
        }
      }, gap * (i + 1)))
    })
  }

  const startLocal = (sc, ctx) => {
    const r = runScenario(sc, m, { ...ctx, lang })
    setChat((c) => (ctx.silent ? c : [...c, { who: 'me', text: r.utterance }]))
    play(r, STEP_MS)
  }

  const startLive = async (sc, ctx) => {
    const utterance = ctx.utterance || sc.utterance(m) // sent to the backend (tested phrasing)
    const shownText = ctx.utterance || sayText(sc, m, lang)
    setChat((c) => [...c, { who: 'me', text: shownText }])
    setBusy(true); setRun(null); setReveal(0)
    const t0 = performance.now()
    try {
      const resp = await callLive(sc, m, { ...ctx, utterance, lang })
      play(responseToRun(sc, m, resp, shownText, performance.now() - t0), 320)
    } catch (e) {
      const missing = e.status === 404
      setChat((c) => [...c, { who: 'ai', text: missing ? 'Ye live endpoint abhi us service par available nahi hai — local demo engine se chala raha hoon.' : `Live service error (${e.message}). Local demo engine se chala raha hoon.`, tone: 'bad' }])
      setBusy(false)
      if (sc.build) startLocal(sc, { ...ctx, silent: true })
    }
  }

  const start = (sc, ctx = {}) => {
    if (busy) return
    if (modeRef.current === 'live' && liveOk(sc)) startLive(sc, ctx)
    else startLocal(sc, ctx)
  }

  // Guided demo: plays the golden path one scenario after another.
  useEffect(() => {
    if (busy || !queue.length) return
    const t = setTimeout(() => {
      const [id, ...rest] = queue
      setQueue(rest)
      const sc = SCENARIOS.find((s) => s.id === id)
      if (sc && (!sc.available || sc.available(m)) && (mode !== 'live' || liveOk(sc))) start(sc)
    }, 1100)
    return () => clearTimeout(t)
  }, [busy, queue])
  const playDemo = () => {
    if (queue.length) return setQueue([])
    reset(mkey, true)
    setQueue(mode === 'live' ? ['settle', 'cb', 'fake', 'shield_edi'] : ['settle', 'cb', 'fake', 'shield_cb', 'shield_edi'])
  }

  const onPreset = (id) => start(SCENARIOS.find((s) => s.id === id))
  const onText = (text) => {
    // Live: the real router (Sarvam LLM + rules on 8003) classifies everything said or typed, and asks back when it
    // doesn't understand. The local keyword matcher used to hijack phrases here (anything with "screenshot"
    // replayed the canned fake-screenshot demo with the demo image).
    if (modeRef.current === 'live') {
      start({ id: 'free', intent: 'ESCALATE_HUMAN', utterance: () => text, build: null }, { utterance: text })
      return
    }
    const id = routeText(text)
    const sc = SCENARIOS.find((s) => s.id === id)
    if (!sc || (sc.available && !sc.available(m))) {
      setChat((c) => [...c, { who: 'me', text }, { who: 'ai', text: 'Maaf kijiye, samajh nahi aaya. Neeche ke quick scenarios try kijiye.' }])
      return
    }
    start(sc, { utterance: text })
  }
  const onUpload = (kind, f) => {
    const sc = SCENARIOS.find((s) => s.id === (kind === 'pod' ? 'cb' : 'fake'))
    if (sc.available && !sc.available(m)) {
      setChat((c) => [...c, { who: 'ai', text: 'Is merchant ka koi chargeback hold nahi hai, PoD ki zaroorat nahi.' }])
      return
    }
    start(sc, { file: f.name, fileObj: f, utterance: kind === 'pod' ? `${f.name} (Proof of Delivery)` : `${f.name} (UPI screenshot)` })
  }
  // Real voice: Sarvam STT (via 8003 /merchant/transcribe) says what was heard; that text then goes through the same
  // path as typing (`handle` also turns a spoken "haan" into the pending sign-off). If nothing usable was heard,
  // the merchant is told so. Never answer a question that wasn't asked.
  const onAudio = async (blob, fallbackText = '', handle = onText) => {
    if (busy) return
    if (modeRef.current !== 'live') {
      setChat((c) => [...c, { who: 'ai', text: tr(lang, 'needLive'), tone: 'bad' }])
      return
    }
    setBusy(true)
    let res = null
    try { res = await transcribe(blob, m.mid, lang) } catch { res = null }
    setBusy(false)
    const heard = (res?.transcript || '').trim() || fallbackText.trim() // browser recognizer only as a fallback
    if (heard) return handle(heard)
    setChat((c) => [...c, { who: 'ai', text: res?.message_hi || tr(lang, 'unclear'), tone: 'bad' }])
  }
  const onConfirm = (item, k) => {
    if (busy) return
    setChat((c) => c.map((x, i) => (i === k ? { ...x, done: true } : x)))
    const cf = item.confirm
    start(SCENARIOS.find((s) => s.id === (cf.kind === 'dispute' ? 'confirm_cb' : 'confirm_edi')), cf.kind === 'dispute' ? { packet: cf.packet } : { offer_id: cf.offer_id, pause_days: cf.pause_days, saved: cf.saved })
  }

  const d = m.d
  const go = (to) => { if (TOPS.includes(to)) { setTab(to); setSub(null) } else setSub(to) }
  const back = () => setSub(null)
  const subs = {
    history: <History d={d} back={back} />,
    soundbox: <Soundbox back={back} />,
    refunds: <Refunds d={d} back={back} />,
    offers: <Offers back={back} />,
    qr: <QR d={d} back={back} />,
  }
  const tabs = {
    home: <Home d={d} go={go} />,
    settlements: <Settlement d={d} />,
    loans: <Loans d={d} />,
    account: <Account d={d} />,
    buddy: <Buddy m={m} L={ledger} chat={chat} busy={busy} mode={mode} onPreset={onPreset} onText={onText} onUpload={onUpload} onConfirm={onConfirm} onAudio={onAudio} run={run} reveal={reveal} onTheme={setDark} speak={speak} setSpeak={setSpeak} lang={lang} setLang={setLang} />,
  }
  const body = (sub && subs[sub]) || tabs[tab]

  return (
    <div className={`cc ${busy ? 'busy' : ''}`}>
      <header className="cc-top">
        <PaytmLogo size={20} />
        <div className="cc-title"><b>AI Teammate for Paytm merchants</b><span className="muted xs">Merchant AI Buddy ⇄ Paytm AI agents · solves problems end to end</span></div>
        <div className="cc-r">
          {mode === 'live' && svc.sarvam && svc.sarvam !== 'live' && (
            <span className="badge warn" title="Sarvam runs without SARVAM_API_KEY: speech recognition and Sarvam voice are off. Add the key to .env and restart.">
              {svc.sarvam === 'mock' ? 'Voice off: Sarvam key missing' : 'Voice off: Sarvam down'}
            </span>
          )}
          {sb.enabled && (
            <span className={`badge ${sb.status === 'live' ? 'ok' : sb.error ? 'warn' : 'info'}`} title={sb.error || 'Supabase Realtime: Paytm ledger rows, read-only'}>
              {sb.status === 'live' ? 'Supabase live' : `Supabase ${sb.status}`}
            </span>
          )}
          <div className="mode">
            <button className={mode === 'local' ? 'on' : ''} onClick={() => switchMode('local')}>Local demo</button>
            <button className={mode === 'live' ? 'on' : ''} disabled={!svc.merchant} onClick={() => switchMode('live')} title={svc.merchant ? 'Use the real services (merchant 8003' + (svc.paytm ? ' + Paytm 8002)' : ', Paytm mocked)') : 'Start the merchant agent on :8003 to enable'}>
              <i className={`dot-s ${svc.merchant ? 'up' : ''}`} />Live services
            </button>
          </div>
          <button className="play" onClick={playDemo}>{queue.length ? '■ Stop demo' : '▶ Play guided demo'}</button>
          <button className="reset" onClick={() => { setQueue([]); reset(mkey, true) }}>Reset</button>
        </div>
      </header>
      <main className="cc-grid">
        <section className="col left">
          <div className={`phone ${dark ? 'dark' : ''}`}>
            <div className="notch" />
            <StatusBar />
            <div className={`content ${tab === 'buddy' && !sub ? 'flex' : ''}`} ref={scroller}>{body}</div>
            <nav className="tabs">
              {TABS.map((t) => (
                <button key={t.id} aria-label={t.label} className={`${tab === t.id && !sub ? 'on' : ''} ${t.center ? 'ctr' : ''}`} onClick={() => go(t.id)}>
                  {t.center ? <span className="qr-fab"><AIMark size={46} /></span> : <t.icon size={24} />}
                  {t.center ? <span className="ghostlbl">.</span> : <span>{t.label}</span>}
                </button>
              ))}
            </nav>
            <div className="home-ind" />
          </div>
        </section>
        <Center run={run} reveal={reveal} busy={busy} onTry={onPreset} />
        <Right m={m} L={ledger} mode={mode} />
      </main>
    </div>
  )
}
