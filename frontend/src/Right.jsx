import React, { useEffect, useState } from 'react'
import { inr } from './data.js'
import { MerchantLogo } from './icons.jsx'

// Dropdown card: header always visible, opens on click, and opens by itself when `watch` changes (new info landed).
function Drop({ title, sub, badge, tone, def, watch, children }) {
  const [open, setOpen] = useState(!!def)
  const first = React.useRef(true)
  useEffect(() => { if (first.current) { first.current = false; return } setOpen(true) }, [watch])
  return (
    <div className={`acc ${open ? 'open' : ''} ${tone || ''}`}>
      <button className="acc-h" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="acc-t"><b>{title}</b><em>{sub}</em></span>
        {badge && <i className="acc-b">{badge}</i>}
        <span className="acc-chev">›</span>
      </button>
      <div className="acc-body"><div>{children}</div></div>
    </div>
  )
}

// Plain words a shop owner uses for each deduction.
const PLAIN = [
  [/chargeback|dispute|held|hold/i, 'On hold (customer dispute)'],
  [/refund/i, 'Customer refund'],
  [/soundbox/i, 'Soundbox rent'],
  [/gst/i, 'GST on fees'],
  [/mdr|fee/i, 'Payment fees'],
]
const plain = (l) => (PLAIN.find(([re]) => re.test(l)) || [0, l])[1]

// "What changed" feed, newest first, built from the ledger itself. Every line says what the AI did, in one sentence.
function changes(L) {
  const out = []
  if (L.chargeback?.status === 'RELEASED') out.push({ k: 'cb', t: `${inr(L.chargeback.amount)} released for ${L.chargeback.order}`, s: 'Delivery proof accepted. It arrives in your next settlement.' })
  if (L.loan.status === 'PAUSED') out.push({ k: 'edi', t: 'Loan EDI paused for 2 days', s: 'No instalment is taken until it restarts.' })
  if (L.loan.status === 'LINK_SENT') out.push({ k: 'edi', t: 'Payment link sent for your EDI', s: 'Pay with one tap to avoid a penalty.' })
  if (L.loan.status === 'QUOTE') out.push({ k: 'edi', t: 'Loan closure quote ready', s: 'You get the no-dues letter after you pay it.' })
  if (L.itc > 0) out.push({ k: 'itc', t: `GST credit of ${inr(L.itc)} noted`, s: 'Added to your GST sheet.' })
  L.refunds.forEach((r) => out.push({ k: 'refund', t: `Refund of ${inr(r.amount)} sent for ${r.order}`, s: 'The duplicate payment went back to the customer.' }))
  L.tickets.forEach((t) => out.push({ k: 'ticket', t: t.reason ? `Support ticket raised: ${t.reason}` : 'Support ticket raised', s: `Reference ${t.id}` }))
  if (L.bank.status === 'LINK_SENT') out.push({ k: 'bank', t: 'Bank update link sent', s: 'Your settlement moves once the new account is verified.' })
  if (L.soundbox.status === 'PICKUP') out.push({ k: 'sb', t: 'Soundbox pickup booked', s: 'Rent stops from the pickup date.' })
  if (L.utrs.some((u) => u.check === 'FAKE')) out.push({ k: 'fraud', t: 'A fake payment was caught', s: 'The money never reached your account. Do not hand over the goods.', bad: true })
  return out.reverse().slice(0, 6)
}

const loanWords = {
  ACTIVE: ['Running normally', 'ok'], PAUSED: ['Paused for 2 days', 'warn'], LINK_SENT: ['Payment link sent', 'info'],
  MANDATE_FIXED: ['Mandate fixed', 'info'], QUOTE: ['Closure quote ready', 'info'],
}
const payWords = (u) => (u.check === 'FAKE' || u.status === 'NOT_FOUND_SUSPECTED_FAKE' ? ['Looks fake', 'bad'] : u.status === 'SUCCESS' ? ['Paid', 'ok'] : u.status === 'PENDING' ? ['Pending', 'warn'] : [String(u.status).toLowerCase().replace(/^./, (c) => c.toUpperCase()), 'info'])

function Pill({ tone = 'ok', children }) { return <span className={`lg-pill ${tone}`}>{children}</span> }
function Row({ k, v, tone }) { return <div className="lg-row"><span>{k}</span><b className={tone || ''}>{v}</b></div> }

export default function Right({ m, L, mode }) {
  const lo = L.loan
  const s = m.d.settlement
  const feed = changes(L)
  const released = L.chargeback?.status === 'RELEASED'
  const deducted = s.deductions.reduce((a, x) => a + (x.key === 'CHARGEBACK_HOLD' && released ? 0 : x.amount), 0)
  const inBank = s.gross - deducted
  const [loanTxt, loanTone] = loanWords[lo.status] || [lo.status, 'info']
  const fakeCount = L.utrs.filter((u) => u.check === 'FAKE' || u.status === 'NOT_FOUND_SUSPECTED_FAKE').length

  return (
    <div className="col right lg">
      <div className="col-h">
        <div className="rh-m"><MerchantLogo d={m.d} size={34} /><div><b>Your ledger</b><div className="muted xs">What changed in Paytm’s books · {m.profile.name}</div></div></div>
        <span className="state done"><i className="live" /> {mode === 'live' ? 'Live' : 'Demo'}</span>
      </div>

      <div className="lg-sum">
        <div><b key={L.verified} className={L.verified ? 'g' : ''}>{L.verified}</b><span>Solved by AI</span></div>
        <div><b key={L.fraud} className={L.fraud ? 'r' : ''}>{L.fraud}</b><span>Fraud blocked</span></div>
        <div><b key={L.deflected}>{L.deflected}</b><span>Tickets avoided</span></div>
      </div>

      <div className="lg-h"><b>Latest changes</b><span>{feed.length ? 'Newest first' : ''}</span></div>
      {feed.length === 0 ? (
        <div className="lg-empty"><b>Nothing has changed yet</b><span>Ask the assistant something. Every fix shows up here, in plain words.</span></div>
      ) : (
        <div className="lg-feed">
          {feed.map((x, i) => (
            <div key={x.k + i} className={`lg-f ${x.bad ? 'bad' : ''}`}>
              <span className="lg-dot">{x.bad ? '!' : '✓'}</span>
              <div><b>{x.t}</b><em>{x.s}</em></div>
            </div>
          ))}
        </div>
      )}

      <div className="lg-h"><b>Your money and accounts</b></div>

      <Drop title="Settlement" sub={`${s.date} · ${L.chargeback && !released ? 'part of it is on hold' : 'all clear'}`} badge={L.chargeback ? (released ? 'Released' : 'On hold') : ''} tone={L.chargeback && !released ? 'esc' : 'good'} def watch={L.chargeback?.status}>
        <div className="lg-3">
          <div><span>You sold</span><b>{inr(s.gross)}</b></div>
          <div><span>Deducted</span><b className="r">−{inr(deducted)}</b></div>
          <div><span>In your bank</span><b className="g">{inr(inBank)}</b></div>
        </div>
        <div className="lg-list">
          {s.deductions.map((x) => {
            const isHold = x.key === 'CHARGEBACK_HOLD'
            return (
              <div key={x.key} className="lg-row">
                <span>{plain(x.label)}{isHold && L.chargeback && <Pill tone={released ? 'ok' : 'warn'}>{released ? 'Released' : 'Held'}</Pill>}</span>
                <b className={isHold && released ? 'g' : ''}>{isHold && released ? '' : '−'}{inr(x.amount)}</b>
              </div>
            )
          })}
        </div>
        {L.chargeback && !released && (
          <div className="lg-note warn"><b>{inr(L.chargeback.amount)} is on hold for {L.chargeback.order}</b><span>Send the delivery proof within 48 hours to get it back.</span></div>
        )}
      </Drop>

      <Drop title="Loan EDI" sub={`${inr(lo.edi)} a day · ${inr(lo.balance)} left to pay`} badge={loanTxt} tone={loanTone === 'warn' ? 'esc' : ''} watch={lo.status}>
        <div className="lg-3">
          <div><span>Daily instalment</span><b>{inr(lo.edi)}</b></div>
          <div><span>Balance</span><b>{inr(lo.balance)}</b></div>
          <div><span>Status</span><b className={loanTone === 'warn' ? 'a' : loanTone === 'ok' ? 'g' : ''}>{loanTxt}</b></div>
        </div>
        {lo.note && <div className="lg-note"><span>{lo.note}</span></div>}
      </Drop>

      <Drop title="Account and devices" sub="Bank, hold and Soundbox" watch={L.bank.status + L.soundbox.status}>
        <div className="lg-list">
          <div className="lg-row"><span>Bank hold on settlement</span><Pill tone="ok">None</Pill></div>
          <div className="lg-row"><span>Settlement bank · {L.bank.acct}</span><Pill tone={L.bank.status === 'LINK_SENT' ? 'warn' : 'ok'}>{L.bank.status === 'LINK_SENT' ? 'Verify pending' : 'Active'}</Pill></div>
          <div className="lg-row"><span>Soundbox · {inr(L.soundbox.rent)}/month</span><Pill tone={L.soundbox.status === 'PICKUP' ? 'info' : 'ok'}>{L.soundbox.status === 'PICKUP' ? 'Pickup booked' : 'Active'}</Pill></div>
          {L.soundbox.note && <div className="lg-note"><span>{L.soundbox.note}</span></div>}
        </div>
      </Drop>

      <Drop title="Payments we checked" sub={`${L.utrs.length} payments${fakeCount ? ` · ${fakeCount} looks fake` : ''}`} badge={fakeCount ? 'Fake found' : ''} tone={fakeCount ? 'bad' : ''} watch={L.utrs.length + ':' + L.utrs.map((u) => u.check).join()}>
        <div className="lg-list">
          {L.utrs.map((u) => {
            const [w, tone] = payWords(u)
            return (
              <div key={u.utr} className={`lg-row two ${tone === 'bad' ? 'bad' : ''}`}>
                <span><b>{inr(u.amount)}</b><em>{u.app} · {u.name}</em><code>{u.utr}</code></span>
                <Pill tone={tone}>{w}</Pill>
              </div>
            )
          })}
        </div>
      </Drop>

      <Drop title="What the AI has learned" sub={`${m.policies ? m.policies.length : 0} habits remembered · ${L.learned} new`}>
        <div className="lg-list">
          {(m.policies || []).map((p, i) => <div key={i} className="lg-learn"><b>{p.intent.replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase())}</b><span>{p.policy}</span></div>)}
          {L.learnedLog.map((t, i) => <div key={'l' + i} className="lg-learn new"><b>New</b><span>{t}</span></div>)}
        </div>
      </Drop>

      {m.profile.connectors && (
        <Drop title="Data you have shared" sub="Only with your permission">
          <div className="lg-list">
            {Object.entries(m.profile.connectors).map(([k, v]) => (
              <div key={k} className="lg-row"><span>{k.replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase())}</span><Pill tone="ok">{v.consent === 'GRANTED' || v.consent_status === 'GRANTED' ? 'Allowed' : 'Active'}</Pill></div>
            ))}
          </div>
        </Drop>
      )}
    </div>
  )
}
