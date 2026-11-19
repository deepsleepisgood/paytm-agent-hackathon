// Builds the Sharma Electronics (PAYTM_MERCH_8821) merchant from the team's real seed data in /data/seed.
// Same shape as the SME merchants in merchants.js, so every screen works unchanged.
import profile from '../../data/seed/merchant_profile.json'
import loan from '../../data/seed/loan.json'
import brk from '../../data/seed/settlement_breakdown_2026-11-18.json'
import strategy from '../../data/seed/strategy_memory.json'
import dailyCsv from '../../data/seed/daily_sales_summary.csv?raw'
import khataCsv from '../../data/seed/khata.csv?raw'
import custCsv from '../../data/seed/customers.csv?raw'
import invCsv from '../../data/seed/inventory.csv?raw'
import ediCsv from '../../data/seed/edi_schedule.csv?raw'
import refundsCsv from '../../data/seed/refunds.csv?raw'
import payablesCsv from '../../data/seed/supplier_payables.csv?raw'
import deviceCsv from '../../data/seed/device_logs.csv?raw'

// Minimal CSV parser with quoted fields.
export function parseCsv(text) {
  const rows = []
  let row = [], cell = '', q = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++ } else if (c === '"') q = false
      else cell += c
    } else if (c === '"') q = true
    else if (c === ',') { row.push(cell); cell = '' }
    else if (c === '\n') { row.push(cell.replace(/\r$/, '')); rows.push(row); row = []; cell = '' }
    else cell += c
  }
  if (cell || row.length) { row.push(cell.replace(/\r$/, '')); rows.push(row) }
  const [head, ...body] = rows
  return body.filter((r) => r.length === head.length).map((r) => Object.fromEntries(head.map((h, i) => [h, r[i]])))
}

const DED_CODE = { MDR: 'MDR_FEE', GST_ON_MDR: 'GST_ON_MDR', REFUND: 'CUSTOMER_REFUND', SOUNDBOX_RENTAL: 'SOUNDBOX_RENTAL', CHARGEBACK_HOLD: 'CHARGEBACK_HOLD' }
const LABEL = { MDR_FEE: 'MDR Fee', GST_ON_MDR: 'GST on MDR (18%)', CUSTOMER_REFUND: 'Customer Refund', SOUNDBOX_RENTAL: 'Soundbox Rental', CHARGEBACK_HOLD: 'Chargeback Hold' }

function insights(daily, inv, payable) {
  const months = ['2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11']
  const monthly = months.map((mo) => daily.filter((d) => d.date.startsWith(mo)).reduce((s, d) => s + Number(d.gross), 0))
  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
  const avg = days.map((wd) => {
    const r = daily.filter((d) => d.weekday === wd)
    return Math.round(r.reduce((s, d) => s + Number(d.gross), 0) / (r.length || 1))
  })
  const wkday = (avg[0] + avg[1] + avg[2] + avg[3]) / 4, wkend = (avg[4] + avg[5] + avg[6]) / 3
  const stock = [...inv].sort((a, b) => Number(b.weekend_stockout_count_6m) - Number(a.weekend_stockout_count_6m)).slice(0, 3)
  return {
    period: 'Jun–Nov 2026',
    months: ['Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov'],
    monthly_sales: monthly,
    weekdays: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    weekday_avg_sales: avg,
    peak_note: `Fri–Sun sells ${(wkend / wkday).toFixed(1)}× the Mon–Thu average; Dhanteras (6 Nov) was the biggest day`,
    cashflow_health: { score: 72, label: 'Watch cash', note: `₹${payable.toLocaleString('en-IN')} supplier payable due Fri · EDI ${Math.round(loan.first_attempt_success_rate * 100)}% on time` },
    growth_suggestions: stock.map((it, i) => ({
      id: 'g' + (i + 1),
      title: `Weekend stock: ${it.name}`,
      hinglish: `Weekend se pehle ${it.name} ka stock badhao — pichle 6 mahine mein ${it.weekend_stockout_count_6m} baar weekend par khatam hua.`,
      hi: `वीकेंड से पहले ${it.name} का स्टॉक बढ़ाइए — पिछले 6 महीनों में ${it.weekend_stockout_count_6m} बार वीकेंड पर खत्म हुआ।`,
      en: `Stock up on ${it.name} before the weekend — it ran out ${it.weekend_stockout_count_6m} times on weekends in the last 6 months.`,
      impact: `${it.weekend_stockout_count_6m} weekend stock-outs`,
    })),
  }
}

export function buildSharma() {
  const daily = parseCsv(dailyCsv)
  const inv = parseCsv(invCsv)
  const payable = 4500
  const ded = brk.deductions.map((x) => ({
    key: DED_CODE[x.type] || x.type,
    label: LABEL[DED_CODE[x.type]] || x.type,
    note: x.type === 'CHARGEBACK_HOLD' ? `${x.source.split(' on ')[0]} · Held · PoD due in 48h` : x.source,
    amount: x.amount,
  }))
  const rails = brk.by_rail
  const mix = [
    { mode: 'CREDIT_CARD', amount: rails.credit_card_and_postpaid.amount, mdr_rate_pct: 2 },
    { mode: 'WALLET_ON_UPI_GT_2K', amount: rails.wallet_on_upi_above_2000.amount, mdr_rate_pct: 1.1 },
    { mode: 'BANK_UPI', amount: rails.upi_p2m.amount, mdr_rate_pct: 0 },
  ]
  // Udhaar (store credit): latest balance per customer from khata.csv.
  const names = Object.fromEntries(parseCsv(custCsv).map((c) => [c.customer_id, c.name]))
  const last = {}
  for (const k of parseCsv(khataCsv)) last[k.customer_id] = Number(k.balance_after)
  const khata = Object.entries(last).filter(([, b]) => b > 0).sort((a, b) => b[1] - a[1])
    .map(([id, balance]) => ({ id, name: names[id] || id, balance }))
  const edi = parseCsv(ediCsv).slice(-7).map((e) => ({ date: e.edi_date, status: e.status }))

  // Things that need the merchant's attention today, straight from the seed data.
  const bounce = [...parseCsv(ediCsv)].reverse().find((e) => e.status === 'BOUNCED' && e.recovery === 'PENDING')
  const refundReq = parseCsv(refundsCsv).find((r) => r.status === 'REQUESTED')
  const payTomorrow = parseCsv(payablesCsv).find((p) => p.payable_id === 'PAY-TOMORROW')
  const dev = parseCsv(deviceCsv)
  const lastDev = dev[dev.length - 1]
  const missed = dev.filter((d) => d.event === 'HEARTBEAT_MISSED' && d.ts >= '2026-11-15').length
  const facts = {
    edi: bounce && { date: bounce.edi_date, amount: Number(bounce.amount), reason: bounce.bounce_reason },
    cash: refundReq && payTomorrow && {
      refund: { order: '#' + refundReq.order_id, amount: Number(refundReq.amount) },
      payable: { supplier: payTomorrow.supplier.split(' ').slice(0, 2).join(' '), amount: Number(payTomorrow.amount), due: payTomorrow.due_date },
      projected: 4700 - Number(refundReq.amount), // README: ₹4,700 collected by 11:30 on 19 Nov minus the refund request
    },
    soundbox: lastDev && { battery: Number(lastDev.battery_health_pct), missed },
  }

  const profileOut = {
    mid: profile.mid, name: profile.name, owner: profile.owner, category: profile.category, segment: 'SMALL_PLUS',
    city: profile.address.city, locality: profile.address.line1,
    bank_account: 'HDFC ••4821',
    gst: { registered: true, gstin: String(profile.gstin).split(' ')[0], scheme: 'REGULAR', itc_eligible: true },
    connectors: profile.connectors, devices: profile.devices,
  }
  const cb = brk.deductions.find((x) => x.type === 'CHARGEBACK_HOLD')
  return {
    slug: 'sharma_electronics',
    mid: profile.mid,
    profile: profileOut,
    insights: insights(daily, inv, payable),
    orders: { orders: [
      { order_id: '#4412', amount: 1500, type: 'REFUND', status: 'PROCESSED' },
      { order_id: '#9981', txn_id: '#9981', amount: cb.amount, type: 'CHARGEBACK', status: 'HELD', pod_required: true, pod_due_hours: 48, delivered: true },
    ] },
    khata,
    facts,
    policies: strategy.learned_policies,
    d: {
      mid: profile.mid,
      logo: '/merchants/sharma_electronics.webp',
      merchant: profile.name,
      settlement: { date: brk.settlement_date, gross: brk.gross, mix, net: brk.net_credit, variance: brk.variance, deductions: ded },
      loan: {
        edi: loan.daily_edi, next: 'Tomorrow 07:00 (eNACH)', balance: loan.loan_balance,
        principal: loan.total_repayable, offer: 50000, lender: loan.lender, history: edi,
      },
      chargeback: { txn: '#9981', order: '#9981', amount: cb.amount, status: 'HELD' },
      transactions: [
        { utr: '632184920111', amount: 1250, app: 'GPay', status: 'SUCCESS', time: '11:03 AM', name: 'Walk-in' },
        { utr: '632184920999', amount: 2400, app: 'PhonePe', status: 'PENDING', time: '06:15 PM', name: 'Walk-in' },
        { utr: 'REF4412', amount: 1500, app: 'Refund', status: 'REFUNDED', time: '12:30 PM', name: 'Order #4412' },
      ],
    },
  }
}
