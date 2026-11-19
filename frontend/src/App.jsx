import React, { useEffect, useRef, useState } from 'react'
import { I, PaytmLogo } from './icons.jsx'
import { SEED, inr } from './data.js'
import { getLedger } from './api.js'

const TABS = [
  { id: 'home', label: 'Home', icon: I.Home },
  { id: 'settlements', label: 'Settlements', icon: I.Bank },
  { id: 'qr', label: 'QR', icon: I.QR, center: true },
  { id: 'loans', label: 'Loan', icon: I.Loan },
  { id: 'account', label: 'Account', icon: I.User },
]
const TOPS = TABS.map((t) => t.id)

function StatusBar() {
  return (
    <div className="statusbar">
      <span>9:41</span>
      <span className="sb-right">
        <span className="bars"><i /><i /><i /><i /></span><span>5G</span><i className="bat" />
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
          <button className="ai-badge" onClick={() => go('ai')} aria-label="AI Teammate"><I.Spark size={14} /><b>AI</b></button>
          <span className="dotwrap"><I.Bell size={22} /><em /></span>
        </div>
      </div>
      <div className="greet">
        <div className="avatar">SE</div>
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
        <div className="row between line"><span>Language</span><b>हिन्दी</b></div>
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
  const pct = Math.round(((100000 - l.balance) / 100000) * 100)
  return (
    <div className="screen">
      <Header title="Business Loan" />
      <div className="card loan">
        <div className="muted">Outstanding balance</div>
        <div className="big">{inr(l.balance)}</div>
        <div className="bar"><i style={{ width: pct + '%' }} /></div>
        <div className="muted sm">{pct}% repaid of ₹1,00,000</div>
      </div>
      <div className="card">
        <div className="row between line"><span>Daily EDI</span><b>{inr(l.edi)}/day</b></div>
        <div className="row between line"><span>Next deduction</span><b>{l.next}</b></div>
        <div className="row between line"><span>Deducted from</span><b>Daily settlement</b></div>
      </div>
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
      <div className="card center-card"><div className="avatar lg">SE</div><b>{d.merchant}</b><div className="muted sm">{d.mid}</div></div>
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

function AI({ back }) {
  return (
    <div className="screen">
      <Header title="AI Teammate" back={back} />
      <div className="card center-card">
        <div className="sb-device"><I.Spark size={44} /></div>
        <b>Your autonomous AI Teammate</b>
        <div className="muted sm">Ask in Hindi or English. Reconcile settlements, verify UTRs, resolve chargebacks. Connects to the agent team on ports 8002/8003.</div>
      </div>
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

/* ---------------- Shell ---------------- */
export default function App() {
  const [tab, setTab] = useState('home')
  const [sub, setSub] = useState(null)
  const [d] = useState(SEED)
  const [live, setLive] = useState(false)
  const scroller = useRef(null)

  useEffect(() => { scroller.current?.scrollTo(0, 0) }, [tab, sub])
  // Pull live state from the Paytm agent (8002) when it's running; fall back to seed data.
  useEffect(() => {
    let off = false
    getLedger().then((l) => { if (!off && l) setLive(true) })
    return () => { off = true }
  }, [])

  const go = (to) => { if (TOPS.includes(to)) { setTab(to); setSub(null) } else setSub(to) }
  const back = () => setSub(null)

  const subs = {
    history: <History d={d} back={back} />,
    soundbox: <Soundbox back={back} />,
    refunds: <Refunds d={d} back={back} />,
    offers: <Offers back={back} />,
    ai: <AI back={back} />,
  }
  const tabs = {
    home: <Home d={d} go={go} />,
    settlements: <Settlement d={d} />,
    qr: <QR d={d} />,
    loans: <Loans d={d} />,
    account: <Account d={d} />,
  }
  const body = (sub && subs[sub]) || tabs[tab]

  return (
    <div className="stage">
      <div className="side">
        <PaytmLogo size={34} />
        <p>Mobile clone · Person 4 frontend</p>
        <div className={`conn ${live ? 'on' : ''}`}>{live ? 'Live: Paytm agent connected' : 'Offline: using seed data'}</div>
      </div>
      <div className="phone">
        <div className="notch" />
        <StatusBar />
        <div className="content" ref={scroller}>{body}</div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={`${tab === t.id && !sub ? 'on' : ''} ${t.center ? 'ctr' : ''}`} onClick={() => go(t.id)}>
              {t.center ? <span className="qr-fab"><t.icon size={26} /></span> : <t.icon size={22} />}
              <span>{t.label}</span>
            </button>
          ))}
        </nav>
        <div className="home-ind" />
      </div>
    </div>
  )
}
