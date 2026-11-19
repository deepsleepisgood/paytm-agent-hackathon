// Local A2A simulation: Merchant Buddy -> Paytm 4-agent mesh. Deterministic so the demo never breaks
// when backends (8001-8003) are offline. Replace `runScenario` with real /merchant/query calls when ready.
import { inr } from './data.js'

const hex = (n) => Math.random().toString(16).slice(2, 2 + n)
const rid = () => 'req_' + hex(8)
const tkt = () => 'TKT-PAYTM-' + (1000 + Math.floor(Math.random() * 9000))
const ded = (m, code) => m.d.settlement.deductions.find((x) => x.key === code)?.amount || 0
const REFUND_ASK = { PAYTM_MERCH_1101: 1200, PAYTM_MERCH_1102: 5800, PAYTM_MERCH_1103: 6500 }
const FAKE_UTR = '632184929999'

const opt = (id, label, score, why) => ({ id, label, score, why })

export const SCENARIOS = [
  {
    id: 'settle', chip: '₹ kahan kata?', intent: 'SETTLEMENT_RECONCILE',
    utterance: (m) => `Kal ₹${m.d.settlement.gross.toLocaleString('en-IN')} sale tha, bank mein ${inr(m.d.settlement.net)} aaya — ${inr(m.d.settlement.variance)} kahan kata?`,
    build(m) {
      const s = m.d.settlement, cb = m.d.chargeback, gst = ded(m, 'GST_ON_MDR'), itc = m.profile.gst.itc_eligible
      return {
        purpose: 'settlement_reconciliation', scope: 'settlement_ledger:read',
        payload: { date: s.date, expected_gross: s.gross, bank_credit: s.net },
        options: [opt('A', 'Sirf total variance batao', 48, 'Fast, but merchant gets no detail'), opt('B', 'Itemized breakdown + flag held chargeback + ITC log', 91, 'Resolves fully, no follow-up call'), opt('C', 'Escalate to human L2', 22, 'Slow, unnecessary for a standard variance')],
        selected: 'B',
        response: { status: 'RESOLVED', deductions: s.deductions.map((x) => ({ code: x.key, amount: x.amount })), variance: s.variance },
        agents: {
          intelligence: { say: `Settlement ${s.date} parsed: ${inr(s.gross)} gross → ${inr(s.net)} net, ${s.deductions.length} deduction lines` },
          risk: { say: `Consent valid · MID match · variance ${((s.variance / s.gross) * 100).toFixed(1)}% of gross, no anomaly` },
          resolution: { say: `Mapped ${inr(s.variance)} to fees, GST, refund, rental${cb ? ' and a held chargeback' : ''}` },
          ledger: itc ? { say: `GST ITC ${inr(gst)} logged to merchant sheet`, effects: [{ t: 'ITC', amount: gst }] } : { say: 'GST ITC not applicable for this merchant (unregistered/composition)' },
        },
        reply: `${inr(s.variance)} kate: MDR ${inr(ded(m, 'MDR_FEE'))}, GST ${inr(gst)}, refund ${inr(ded(m, 'CUSTOMER_REFUND'))}, Soundbox ₹149${cb ? `, aur ${inr(cb.amount)} chargeback hold (${cb.order})` : ''}.${cb ? ' Delivery proof bhejo, hold khul jayega.' : ''}`,
        win: true,
      }
    },
  },
  {
    id: 'utr', chip: 'UTR pending', intent: 'UTR_VERIFY',
    utterance: (m) => `UTR ${m.d.transactions.find((t) => t.status === 'PENDING').utr} ka payment check karo`,
    build(m) {
      const t = m.d.transactions.find((x) => x.status === 'PENDING')
      return {
        purpose: 'utr_verification', scope: 'upi_ledger:read',
        payload: { utr_number: t.utr },
        options: [opt('A', 'Merchant ko wait karne bolo', 40, 'No evidence given to merchant'), opt('B', 'Check NPCI status + give T+1 timeline and safe advice', 89, 'Merchant knows exactly what to do'), opt('C', 'Escalate to human L2', 18, 'Overkill for a pending UPI')],
        selected: 'B',
        response: { status: 'PENDING', utr: t.utr, amount: t.amount, payer_app: t.app, note: 'NPCI T+1 auto-reversal' },
        agents: {
          intelligence: { say: `UTR ${t.utr} matched across payer apps → ${t.app}, ${inr(t.amount)}` },
          risk: { say: 'UTR format valid (12 digits) · not tampered · amount matches ledger' },
          resolution: { say: 'Status PENDING — NPCI will settle or auto-reverse by T+1' },
          ledger: { say: 'Check recorded on UTR table', effects: [{ t: 'UTR_CHECK', utr: t.utr, result: 'PENDING' }] },
        },
        reply: `UTR ${t.utr}: ${inr(t.amount)} (${t.app}) abhi PENDING hai. NPCI T+1 tak settle ya auto-reverse ho jayega. Tab tak saamaan mat dena.`,
        win: true,
      }
    },
  },
  {
    id: 'fake', chip: 'Fake screenshot', intent: 'UTR_VERIFY',
    utterance: () => 'Customer ne ye screenshot dikhaya, paisa aaya ya nahi?',
    build(m, ctx) {
      const amt = m.d.transactions.find((x) => x.status === 'PENDING').amount
      return {
        purpose: 'utr_verification', scope: 'upi_ledger:read',
        payload: { doc_type: 'upi_screenshot', file: ctx?.file || 'fake_upi.png', extracted_fields: { utr_number: FAKE_UTR, amount: amt }, confidence: 0.94 },
        options: [opt('A', 'Trust the screenshot', 8, 'High fraud exposure'), opt('B', 'Verify UTR against acquiring ledger (all payer apps)', 96, 'Catches tampered screenshots'), opt('C', 'Escalate to human L2', 30, 'Too slow while customer waits')],
        selected: 'B',
        response: { status: 'NOT_FOUND_SUSPECTED_FAKE', utr: FAKE_UTR },
        agents: {
          intelligence: { say: `Vision extracted UTR ${FAKE_UTR}, ${inr(amt)} from screenshot` },
          risk: { say: 'UTR not found in GPay/PhonePe/Paytm/BHIM ledgers → SUSPECTED FAKE', tone: 'bad', effects: [{ t: 'FRAUD' }] },
          resolution: { say: 'Merchant alert prepared: do not release goods' },
          ledger: { say: 'Fraud counter +1 · UTR flagged', effects: [{ t: 'UTR_ADD', row: { utr: FAKE_UTR, amount: amt, app: 'PhonePe', status: 'NOT_FOUND_SUSPECTED_FAKE', time: 'now', name: 'Screenshot upload' } }] },
        },
        reply: `⚠️ Ye UTR hamare ledger mein nahi hai — screenshot nakli lag raha hai. Saamaan mat dena!`,
        win: true, tone: 'bad',
      }
    },
  },
  {
    id: 'cb', chip: 'Chargeback PoD', intent: 'CHARGEBACK_RESOLVE',
    available: (m) => !!m.d.chargeback,
    utterance: (m) => `Haan, delivery proof bhejo (Order ${m.d.chargeback.order})`,
    build(m, ctx) {
      const c = m.d.chargeback
      return {
        purpose: 'chargeback_resolution', scope: 'chargeback:write',
        payload: { doc_type: 'pod', file: ctx?.file || `pod_${c.order.replace('#', '')}.png`, extracted_fields: { order_id: c.order, status: 'DELIVERED' }, confidence: 0.96 },
        options: [opt('A', 'Wait for customer to withdraw', 20, 'Cash stuck, may lose dispute'), opt('B', 'Submit PoD to Paytm, auto-release hold', 94, 'Fastest recovery'), opt('C', 'Accept chargeback', 12, 'Loses the amount')],
        selected: 'B',
        response: { status: 'RELEASED', order_id: c.order, release_eta: 'T+1', amount: c.amount },
        agents: {
          intelligence: { say: `PoD read: order ${c.order} DELIVERED (confidence 96%)` },
          risk: { say: 'Order id matches the held txn · PoD within 48h window' },
          resolution: { say: `Dispute won — release ${inr(c.amount)} hold`, effects: [{ t: 'CB_RELEASE' }] },
          ledger: { say: `Hold ${c.order} HELD → RELEASED (T+1)`, effects: [{ t: 'DEFLECT' }] },
        },
        reply: `Delivery proof mil gaya (Order ${c.order}). ${inr(c.amount)} ka hold RELEASED — T+1 mein bank mein aa jayega.`,
        win: true,
      }
    },
  },
  {
    id: 'refund', chip: 'Refund karna hai', intent: 'REFUND_MANAGE',
    utterance: (m) => `Customer ko ${inr(REFUND_ASK[m.mid] || 6500)} wapas karna hai`,
    build(m) {
      const amt = REFUND_ASK[m.mid] || 6500, auto = amt <= 5000, id = tkt(), order = '#R-' + (3000 + (amt % 900))
      return {
        purpose: 'refund_management', scope: 'refund:write',
        payload: { order_id: order, amount: amt },
        options: [opt('A', 'Refund instantly with no checks', 30, 'Policy risk above ₹5,000'), opt('B', 'Auto-refund (≤ ₹5,000 policy)', auto ? 92 : 20, auto ? 'Within autonomous limit' : 'Above limit, not allowed'), opt('C', 'Escalate to human (> ₹5,000)', auto ? 25 : 90, auto ? 'Unneeded delay' : 'Required by policy')],
        selected: auto ? 'B' : 'C',
        response: auto ? { status: 'REFUND_INITIATED', order_id: order, amount: amt } : { status: 'ESCALATED', ticket: id },
        agents: {
          intelligence: { say: `Refund request ${inr(amt)} for ${order}` },
          risk: { say: auto ? 'Within ₹5,000 autonomous limit' : 'Above ₹5,000 → human approval required', tone: auto ? undefined : 'warn' },
          resolution: { say: auto ? 'Refund approved' : `Pre-filled L2 ticket ${id}` },
          ledger: auto
            ? { say: `Refund ${inr(amt)} initiated`, effects: [{ t: 'REFUND_AUTO', order, amount: amt }, { t: 'DEFLECT' }] }
            : { say: `Ticket ${id} created`, effects: [{ t: 'TICKET', id, reason: `Refund ${inr(amt)} > ₹5,000` }] },
        },
        reply: auto ? `${inr(amt)} ka refund shuru kar diya (${order}). Customer ko 1–2 din mein mil jayega.` : `${inr(amt)} ₹5,000 se upar hai, isliye L2 ticket ${id} bana diya. Team jaldi approve karegi.`,
        win: auto,
      }
    },
  },
  {
    id: 'edi', chip: 'Loan EDI fail', intent: 'FEE_GST_LOAN',
    utterance: () => 'Mera loan EDI mandate fail ho gaya',
    build(m) {
      const e = m.d.loan.edi
      return {
        purpose: 'loan_edi_support', scope: 'lending_ledger:write',
        payload: { topic: 'EDI_MANDATE_FAIL', edi_per_day: e },
        options: [opt('A', 'Wait for automatic retry tomorrow', 38, 'Risk of penalty / credit flag'), opt('B', 'Pause EDI, fix e-mandate, resume with no penalty', 93, 'Protects merchant credit'), opt('C', 'Escalate to lending ops', 35, 'Slower than needed')],
        selected: 'B',
        response: { status: 'MANDATE_FIXED', edi_per_day: e },
        agents: {
          intelligence: { say: `EDI ${inr(e)}/day debit bounced · e-mandate registration invalid` },
          risk: { say: 'Penalty risk detected → pausing EDI', tone: 'warn', effects: [{ t: 'LOAN', status: 'PAUSED' }] },
          resolution: { say: 'Re-mandate link sent on Paytm for Business, bounce charge waived' },
          ledger: { say: `Mandate verified · EDI ${inr(e)} resumes at next settlement`, effects: [{ t: 'LOAN', status: 'MANDATE_FIXED' }] },
        },
        reply: `Aapka ${inr(e)}/din ka EDI mandate fail hua tha. Maine pause karke theek kar diya (MANDATE_FIXED). Koi penalty nahi, kal se EDI dobara chalega.`,
        win: true,
      }
    },
  },
  {
    id: 'growth', chip: 'Business badhao', intent: 'FEE_GST_LOAN',
    utterance: () => 'Mere pichle 6 mahine ke data se business badhane ka suggestion do',
    build(m) {
      const i = m.insights, ms = i.monthly_sales, pct = Math.round(((ms[ms.length - 1] - ms[0]) / ms[0]) * 100)
      const [g1, g2] = i.growth_suggestions
      return {
        purpose: 'business_insights', scope: 'sales_history:read',
        payload: { topic: 'GROWTH_SUGGESTION', period: i.period },
        options: [opt('A', 'Generic 10% discount on everything', 35, 'Cuts margin, ignores your pattern'), opt('B', 'Data-driven: target peak/dip + working-capital offer', 93, 'Uses your own 6-month data'), opt('C', 'Push a loan upsell', 41, 'Not what the merchant asked')],
        selected: 'B',
        response: { status: 'RESOLVED', trend_pct: pct, suggestions: i.growth_suggestions.map((g) => g.id) },
        agents: {
          intelligence: { say: `6-month sales ${pct >= 0 ? '+' : ''}${pct}% · ${i.peak_note}` },
          risk: { say: `Cashflow health ${i.cashflow_health.score}/100 (${i.cashflow_health.label}) · ${i.cashflow_health.note}` },
          resolution: { say: `Top play: ${g1.title} (${g1.impact})` },
          ledger: { say: 'Strategy saved to learning memory' },
        },
        reply: `Pichle 6 mahine mein sale ${pct}% badhi. ${g1.hinglish} Saath mein: ${g2.hinglish}`,
        win: true,
      }
    },
  },
  {
    id: 'soundbox', chip: 'Soundbox kharab', intent: 'ESCALATE_HUMAN',
    utterance: () => 'Soundbox bol nahi raha, kaam nahi kar raha',
    build() {
      const id = tkt()
      return {
        purpose: 'device_support', scope: 'ticketing:write',
        payload: { topic: 'SOUNDBOX_HARDWARE' },
        options: [opt('A', 'Send restart guide', 40, 'Device not responding to restart'), opt('B', 'Remote diagnostics', 45, 'Offline device, cannot reach'), opt('C', 'Create pre-filled L2 hardware ticket', 90, 'Hardware needs an engineer')],
        selected: 'C',
        response: { status: 'ESCALATED', ticket: id },
        agents: {
          intelligence: { say: 'Device SB offline for 2h · no heartbeat' },
          risk: { say: 'Hardware fault pattern → human required', tone: 'warn' },
          resolution: { say: `Pre-filled ticket ${id} with device id and last seen time` },
          ledger: { say: `Ticket ${id} created`, effects: [{ t: 'TICKET', id, reason: 'Soundbox hardware' }] },
        },
        reply: `Soundbox hardware issue lag raha hai. L2 ticket ${id} bana diya, engineer 24 ghante mein contact karega.`,
        win: false,
      }
    },
  },
]

export function runScenario(sc, m, ctx = {}) {
  const b = sc.build(m, ctx)
  const consent = { token: 'cns_' + hex(12), purpose: b.purpose, scope: b.scope, ttl_min: 15, issued: new Date().toISOString().slice(11, 19) + 'Z', mid: m.mid }
  const request = { request_id: rid(), mid: m.mid, intent: sc.intent, payload: b.payload, consent_token: consent.token }
  const A = b.agents
  const steps = [
    { key: 'input', title: 'Input understood', say: `intent=${sc.intent} · lang=hi-IN`, ms: 120 },
    { key: 'consent', title: 'DPDP consent', consent, ms: 90 },
    { key: 'eval', title: 'Intervention evaluation', options: b.options, selected: b.selected, ms: 340 },
    { key: 'dispatch', title: 'A2A dispatch', request, response: b.response, ms: 210 },
    { key: 'intelligence', title: 'Intelligence', ...A.intelligence, ms: 260 },
    { key: 'risk', title: 'Risk', ...A.risk, ms: 180 },
    { key: 'resolution', title: 'Resolution', ...A.resolution, ms: 310 },
    { key: 'ledger', title: 'Ledger Ops', ...A.ledger, ms: 150 },
    {
      key: 'reply', title: 'Reply to merchant', reply: b.reply, tone: b.tone, ms: 95,
      effects: b.win ? [{ t: 'OUTCOME' }, { t: 'LEARN', text: `${sc.intent}: option ${b.selected} reinforced` }] : [],
    },
  ]
  return { sc, utterance: ctx.utterance || sc.utterance(m), steps, reply: b.reply }
}

export function routeText(text) {
  const t = text.toLowerCase()
  const has = (...k) => k.some((x) => t.includes(x))
  if (has('edi', 'mandate')) return 'edi'
  if (has('suggest', 'badhane', 'badhao', '6 mahine', 'growth')) return 'growth'
  if (has('screenshot', 'fake', 'nakli')) return 'fake'
  if (has('utr', 'pending', 'paisa aaya')) return 'utr'
  if (has('chargeback', 'delivery', 'proof', 'pod', 'hold')) return 'cb'
  if (has('refund', 'wapas')) return 'refund'
  if (has('soundbox', 'speaker', 'bol nahi', 'kharab')) return 'soundbox'
  if (has('settlement', 'kata', 'kat ', 'bank mein', 'sale')) return 'settle'
  return null
}

export function initLedger(m) {
  return {
    chargeback: m.d.chargeback ? { ...m.d.chargeback, status: 'HELD' } : null,
    loan: { status: 'ACTIVE', edi: m.d.loan.edi, balance: m.d.loan.balance },
    utrs: m.d.transactions.filter((t) => t.status !== 'REFUNDED').map((t) => ({ ...t, check: null })),
    refunds: [], tickets: [], itc: 0, verified: 0, learned: 0, learnedLog: [], deflected: 0, fraud: 0,
  }
}

export function applyEffects(L, effects = []) {
  let s = { ...L }
  for (const e of effects) {
    if (e.t === 'ITC') s.itc += e.amount
    if (e.t === 'CB_RELEASE' && s.chargeback) s.chargeback = { ...s.chargeback, status: 'RELEASED' }
    if (e.t === 'LOAN') s.loan = { ...s.loan, status: e.status }
    if (e.t === 'UTR_CHECK') s.utrs = s.utrs.map((u) => (u.utr === e.utr ? { ...u, check: e.result } : u))
    if (e.t === 'UTR_ADD') s.utrs = [{ ...e.row, check: 'FAKE' }, ...s.utrs]
    if (e.t === 'FRAUD') s.fraud += 1
    if (e.t === 'TICKET') s.tickets = [{ id: e.id, reason: e.reason }, ...s.tickets]
    if (e.t === 'DEFLECT') s.deflected += 1
    if (e.t === 'REFUND_AUTO') s.refunds = [{ order: e.order, amount: e.amount }, ...s.refunds]
    if (e.t === 'OUTCOME') s.verified += 1
    if (e.t === 'LEARN') { s.learned += 1; s.learnedLog = [e.text, ...s.learnedLog].slice(0, 4) }
  }
  return s
}
