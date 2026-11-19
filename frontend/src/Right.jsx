import React from 'react'
import { inr } from './data.js'

function Waterfall({ m, L }) {
  const s = m.d.settlement
  const rows = []
  let run = s.gross
  rows.push({ label: 'Gross sales', amount: s.gross, start: 0, end: s.gross, kind: 'total' })
  for (const x of s.deductions) {
    const released = x.key === 'CHARGEBACK_HOLD' && L.chargeback?.status === 'RELEASED'
    rows.push({ label: x.label, amount: x.amount, start: run - x.amount, end: run, kind: released ? 'released' : x.key === 'CHARGEBACK_HOLD' ? 'hold' : 'ded', note: released ? 'Released T+1' : undefined })
    if (!released) run -= x.amount
  }
  rows.push({ label: 'Bank credit', amount: run, start: 0, end: run, kind: 'net' })
  const pct = (v) => (v / s.gross) * 100
  return (
    <div className="rcard">
      <div className="r-h"><b>Settlement waterfall</b><span className="muted xs">{s.date}</span></div>
      {rows.map((r, i) => (
        <div key={i} className="wf">
          <div className="wf-l"><span>{r.label}</span><em>{r.note}</em></div>
          <div className="wf-track"><i className={r.kind} style={{ left: pct(Math.min(r.start, r.end)) + '%', width: Math.max(pct(Math.abs(r.end - r.start)), 1.6) + '%' }} /></div>
          <div className={`wf-a ${r.kind}`}>{r.kind === 'ded' || r.kind === 'hold' ? '−' : ''}{inr(r.amount)}</div>
        </div>
      ))}
    </div>
  )
}

export default function Right({ m, L, mode }) {
  const lo = L.loan
  const stat = { ACTIVE: 'ok', PAUSED: 'warn', MANDATE_FIXED: 'info', LINK_SENT: 'info', QUOTE: 'info' }[lo.status]
  return (
    <div className="col right">
      <div className="col-h">
        <div><b>What changed in Paytm’s books</b><div className="muted xs">{m.profile.name} · {m.mid}</div></div>
        <span className="state done"><i className="live" /> {mode === 'live' ? 'Live ledger' : 'Demo ledger'}</span>
      </div>

      <div className="sec">Impact so far</div>
      <div className="kpis">
        <div className="kpi k1"><b key={L.verified}>{L.verified}</b><span>Solved by AI</span></div>
        <div className="kpi k2"><b key={L.learned}>{L.learned}</b><span>Strategies learned</span></div>
        <div className="kpi"><b key={L.deflected}>{L.deflected}</b><span>Tickets avoided</span></div>
        <div className="kpi k4"><b key={L.fraud}>{L.fraud}</b><span>Frauds blocked</span></div>
      </div>
      {L.learnedLog.length > 0 && (
        <div className="learn">{L.learnedLog.map((t, i) => <div key={i}>{t}</div>)}</div>
      )}

      <div className="sec">Money</div>
      <Waterfall m={m} L={L} />

      {L.chargeback && (
        <div className="rcard row-card">
          <div><b>Chargeback {L.chargeback.order}</b><div className="muted xs">{inr(L.chargeback.amount)} · PoD due 48h</div></div>
          <span className={`st ${L.chargeback.status === 'HELD' ? 'warn' : 'ok'}`}>{L.chargeback.status === 'HELD' ? 'HELD' : 'RELEASED — T+1'}</span>
        </div>
      )}

      <div className="sec">Loan, account & payments</div>
      <div className="rcard">
        <div className="r-h"><b>Loan EDI</b><span className={`st ${stat}`}>{lo.status}</span></div>
        <div className="steps3">
          {[['ACTIVE', 'ACTIVE'], ['LINK_SENT', 'UPI LINK SENT'], ['PAUSED', 'PAUSED'], ['QUOTE', 'CLOSURE QUOTE']].map(([k, lab]) => <span key={k} className={lo.status === k ? 'on ' + k : ''}>{lab}</span>)}
        </div>
        {lo.note && <div className="learn">{lo.note}</div>}
        <div className="kv2"><span>Daily EDI</span><b>{inr(lo.edi)}</b><span>Balance</span><b>{inr(lo.balance)}</b></div>
      </div>

      <div className="rcard">
        <div className="r-h"><b>Account & device status</b></div>
        <div className="sts"><span>Bank hold</span><span className="st ok">NONE</span></div>
        <div className="sts"><span>Settlement bank · {L.bank.acct}</span><span className={`st ${L.bank.status === 'LINK_SENT' ? 'warn' : 'ok'}`}>{L.bank.status === 'LINK_SENT' ? 'VERIFY PENDING' : 'ACTIVE'}</span></div>
        <div className="sts"><span>Soundbox rent {inr(L.soundbox.rent)}/mo{L.soundbox.note ? ` · ${L.soundbox.note}` : ''}</span><span className={`st ${L.soundbox.status === 'PICKUP' ? 'info' : 'ok'}`}>{L.soundbox.status === 'PICKUP' ? 'PICKUP · RENT STOPS' : 'ACTIVE'}</span></div>
      </div>

      {m.profile.connectors && (
        <div className="rcard">
          <div className="r-h"><b>Connected data sources</b><span className="muted xs">DPDP consent</span></div>
          {Object.entries(m.profile.connectors).map(([k, v]) => (
            <div key={k} className="sts"><span>{k.replace(/_/g, ' ')}</span><span className="st ok">{v.consent === 'GRANTED' || v.consent_status === 'GRANTED' ? 'GRANTED' : 'ACTIVE'}</span></div>
          ))}
        </div>
      )}

      {m.policies && (
        <div className="rcard">
          <div className="r-h"><b>What the AI already learned</b><span className="muted xs">strategy memory</span></div>
          {m.policies.map((p, i) => <div key={i} className="pol"><b>{p.intent.replace(/_/g, ' ')}</b><span>{p.policy}</span></div>)}
        </div>
      )}

      <div className="rcard">
        <div className="r-h"><b>UTR verification</b><span className="muted xs">{L.utrs.length} rows</span></div>
        <table className="utr">
          <tbody>
            {L.utrs.map((u) => (
              <tr key={u.utr} className={u.check === 'FAKE' ? 'fake' : ''}>
                <td><code>{u.utr}</code><div className="muted xs">{u.app} · {u.name}</div></td>
                <td className="r">{inr(u.amount)}</td>
                <td><span className={`st ${u.status === 'SUCCESS' ? 'ok' : u.status === 'PENDING' ? 'warn' : 'bad'}`}>{u.status === 'NOT_FOUND_SUSPECTED_FAKE' ? 'FAKE' : u.status}</span>{u.check === 'PENDING' && <div className="xs muted">✓ checked</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(L.tickets.length > 0 || L.refunds.length > 0 || L.itc > 0) && (
        <div className="rcard">
          <div className="r-h"><b>Actions taken</b></div>
          {L.itc > 0 && <div className="act">GST ITC logged <b>{inr(L.itc)}</b></div>}
          {L.refunds.map((r) => <div key={r.order} className="act">Auto-refund {r.order} <b>{inr(r.amount)}</b></div>)}
          {L.tickets.map((t) => <div key={t.id} className="act"><b>{t.id}</b> · {t.reason}</div>)}
        </div>
      )}
    </div>
  )
}
