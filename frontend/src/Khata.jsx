import React from 'react'
import { inr } from './data.js'

const MODE = { BANK_UPI: 'UPI sales (bank)', WALLET_ON_UPI_GT_2K: 'Wallet-on-UPI sales', CREDIT_CARD: 'Card sales' }

// Builds daily reconciled entries (settlement day + live post-settlement adjustments) from merchant data + ledger state.
export function buildKhata(m, L) {
  const s = m.d.settlement, itc = m.profile.gst.itc_eligible
  const main = [], adj = []
  for (const x of s.mix || []) main.push({ p: MODE[x.mode] || x.mode, v: 'Sales', cr: x.amount })
  for (const x of s.deductions) {
    if (x.key === 'MDR_FEE') main.push({ p: 'MDR fee (payment gateway)', v: 'Payment', dr: x.amount })
    else if (x.key === 'GST_ON_MDR') main.push({ p: itc ? 'GST input credit (ITC) on MDR' : 'GST on MDR (no ITC)', v: 'Journal', dr: x.amount })
    else if (x.key === 'CUSTOMER_REFUND') main.push({ p: `Credit note · refund ${x.note.split(' · ')[0]}`, v: 'Credit note', dr: x.amount })
    else if (x.key === 'SOUNDBOX_RENTAL') main.push({ p: 'Soundbox rental', v: 'Payment', dr: x.amount })
    else if (x.key === 'CHARGEBACK_HOLD') main.push({ p: `Chargeback hold ${x.note.split(' · ')[0]}`, v: 'Receivable', dr: x.amount, pending: true })
  }
  const net = s.net
  main.push({ p: 'Settlement received in bank', v: 'Receipt', dr: net })
  if (L.chargeback?.status === 'RELEASED') adj.push({ p: `Chargeback ${L.chargeback.order} released (T+1)`, v: 'Receipt', cr: 0, dr: L.chargeback.amount })
  if (L.soundbox.status === 'REFUNDED') adj.push({ p: 'Soundbox rent refund (billing error)', v: 'Debit note', dr: L.soundbox.rent })
  for (const r of L.refunds) adj.push({ p: `Credit note · refund ${r.order}`, v: 'Credit note', cr: r.amount })
  if (L.hold.status === 'RELEASED') adj.push({ p: 'Settlement hold released', v: 'Receipt', dr: L.hold.amount })
  if (L.loan.status === 'NOC_ISSUED') adj.push({ p: 'Loan settled · NOC issued', v: 'Payment', cr: Math.round(m.d.loan.balance * 0.7 / 100) * 100 })
  const sales = (s.mix || []).reduce((a, x) => a + x.amount, 0) || s.gross
  const deds = s.deductions.reduce((a, x) => a + x.amount, 0)
  const gst = s.deductions.find((x) => x.key === 'GST_ON_MDR')?.amount || 0
  const mdr = s.deductions.find((x) => x.key === 'MDR_FEE')?.amount || 0
  return { main, adj, sales, deds, net, gst, mdr, ok: sales - deds === net }
}

function csv(m, K) {
  const rows = [['Date', 'Particulars', 'Voucher', 'Debit', 'Credit', 'Status']]
  const date = m.d.settlement.date
  K.main.forEach((r) => rows.push([date, r.p, r.v, r.dr || '', r.cr || '', r.pending ? 'Held' : 'Reconciled']))
  K.adj.forEach((r) => rows.push([date, r.p, r.v, r.dr || '', r.cr || '', 'Post-settlement']))
  return rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
}

export default function Khata({ m, L, onClose }) {
  const K = buildKhata(m, L)
  const g = m.profile.gst
  const download = () => {
    const url = URL.createObjectURL(new Blob([csv(m, K)], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url; a.download = `khata_${m.slug}_${m.d.settlement.date}.csv`; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 500)
  }
  return (
    <div className="sheet">
      <div className="sh-h"><div><b>📊 Khata & Tally Export</b><div className="muted xs">{m.profile.name} · {m.d.settlement.date}</div></div><button className="x" onClick={onClose}>✕</button></div>
      <div className="sh-b">
        <div className="gst">
          <div className="g-h"><b>GST-ready summary</b><span className={`st ${g.registered ? 'ok' : 'warn'}`}>{g.registered ? g.scheme : 'UNREGISTERED'}</span></div>
          <div className="g-r"><span>GSTIN</span><b>{g.gstin || 'Not registered'}</b></div>
          <div className="g-r"><span>Total sales</span><b>{inr(K.sales)}</b></div>
          <div className="g-r"><span>MDR fee</span><b>{inr(K.mdr)}</b></div>
          <div className="g-r"><span>GST on MDR</span><b>{inr(K.gst)}</b></div>
          <div className="g-r"><span>ITC claimable</span><b className={g.itc_eligible ? 'green' : 'red'}>{g.itc_eligible ? inr(K.gst) : '₹0 (not eligible)'}</b></div>
          <div className="g-r"><span>ITC logged in books</span><b>{inr(L.itc)}</b></div>
        </div>

        <div className="kt-h"><b>Daily reconciled entries</b><span className={`st ${K.ok ? 'ok' : 'bad'}`}>{K.ok ? 'Reconciled ✓' : 'Mismatch'}</span></div>
        <table className="kt">
          <thead><tr><th>Particulars</th><th>Dr</th><th>Cr</th></tr></thead>
          <tbody>
            {K.main.map((r, i) => (
              <tr key={i} className={r.pending ? 'pend' : ''}><td>{r.p}<div className="muted xs">{r.v}{r.pending ? ' · held' : ''}</div></td><td>{r.dr ? inr(r.dr) : ''}</td><td>{r.cr ? inr(r.cr) : ''}</td></tr>
            ))}
          </tbody>
        </table>
        <div className="eq">{inr(K.sales)} sales − {inr(K.deds)} deductions = {inr(K.net)} bank credit</div>

        {K.adj.length > 0 && (
          <>
            <div className="kt-h"><b>Post-settlement adjustments</b><span className="muted xs">from live actions</span></div>
            <table className="kt">
              <tbody>
                {K.adj.map((r, i) => (
                  <tr key={i} className="adj"><td>{r.p}<div className="muted xs">{r.v}</div></td><td>{r.dr ? inr(r.dr) : ''}</td><td>{r.cr ? inr(r.cr) : ''}</td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
      <div className="sh-f"><button className="cta" onClick={download}>⬇ Export CSV (Tally / Excel)</button></div>
    </div>
  )
}
