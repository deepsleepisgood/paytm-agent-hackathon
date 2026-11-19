// Local A2A simulation: Merchant Buddy -> Paytm 4-agent mesh. Deterministic so the demo never breaks
// when backends (8001-8003) are offline. Replace `runScenario` with real /merchant/query calls when ready.
import { inr } from './data.js'

const hex = (n) => Math.random().toString(16).slice(2, 2 + n)
const rid = () => 'req_' + hex(8)
const tkt = () => 'TKT-PAYTM-' + (1000 + Math.floor(Math.random() * 9000))
const ded = (m, code) => m.d.settlement.deductions.find((x) => x.key === code)?.amount || 0
const REFUND_ASK = { PAYTM_MERCH_1101: 1200, PAYTM_MERCH_1102: 5800, PAYTM_MERCH_1103: 6500 }
const FAKE_UTR = '632184929999'
const HOLD_AMT = { PAYTM_MERCH_1101: 3200, PAYTM_MERCH_1102: 18500, PAYTM_MERCH_1103: 18500 }

const opt = (id, label, score, why) => ({ id, label, score, why })

export const CONTRACT_INTENTS = ['SETTLEMENT_RECONCILE', 'UTR_VERIFY', 'CHARGEBACK_RESOLVE', 'REFUND_MANAGE', 'FEE_GST_LOAN', 'ESCALATE_HUMAN']
export const liveOk = (sc) => CONTRACT_INTENTS.includes(sc.intent)

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
        reply: `Ye UTR hamare ledger mein nahi hai — screenshot nakli lag raha hai. Saamaan mat dena!`,
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
  {
    id: 'hold', chip: 'Settlement hold', intent: 'SETTLEMENT_HOLD_UNBLOCK',
    utterance: (m) => `Mera ${inr(HOLD_AMT[m.mid] || 18500)} settlement bank/KYC hold pe kyun hai?`,
    build(m) {
      const amt = HOLD_AMT[m.mid] || 18500
      return {
        purpose: 'settlement_hold_review', scope: 'settlement_ledger:write',
        payload: { topic: 'SETTLEMENT_HOLD', amount: amt },
        options: [opt('A', 'Tell merchant to wait for bank', 25, 'No action, cash stays blocked'), opt('B', 'Diagnose hold, auto-verify KYC on file, request release', 92, 'Unblocks cash the same day'), opt('C', 'Escalate to compliance', 34, 'Slow for a name-mismatch hold')],
        selected: 'B',
        response: { status: 'HOLD_RELEASED', amount: amt, release: 'next settlement' },
        agents: {
          intelligence: { say: `Hold found: ${inr(amt)} · reason: bank account name mismatch (KYC re-verification pending)` },
          risk: { say: 'KYC documents on file valid · no AML / fraud flag · release permitted' },
          resolution: { say: 'Penny-drop re-verification passed → release approved' },
          ledger: { say: `Hold ${inr(amt)} HELD → RELEASED (next settlement)`, effects: [{ t: 'HOLD_RELEASE' }, { t: 'DEFLECT' }] },
        },
        reply: `Aapka ${inr(amt)} bank-name mismatch ki wajah se KYC hold par tha. Documents verify ho gaye, hold hata diya — agle settlement mein aa jayega.`,
        win: true,
      }
    },
  },
  {
    id: 'sbrent', chip: 'Soundbox rent', intent: 'SOUNDBOX_BILLING_REFUND',
    utterance: () => 'Soundbox wapas kar diya phir bhi ₹149 rent kat raha hai',
    build() {
      return {
        purpose: 'billing_dispute', scope: 'billing:write',
        payload: { topic: 'SOUNDBOX_RENT_AFTER_RETURN', amount: 149 },
        options: [opt('A', 'Ask merchant for return receipt', 30, 'Return is already scanned in logistics'), opt('B', 'Match return scan, stop rental, refund ₹149', 94, 'Fixes billing and refunds in one go'), opt('C', 'Escalate to human L2', 28, 'Not needed, return is verified')],
        selected: 'B',
        response: { status: 'RENT_STOPPED', refund: 149 },
        agents: {
          intelligence: { say: 'Return scan found for the device · rent still billing after return' },
          risk: { say: 'Billing error confirmed · refund ≤ ₹5,000 policy → autonomous' },
          resolution: { say: 'Stop rental, refund ₹149 to settlement' },
          ledger: { say: 'Rental stopped · ₹149 refunded', effects: [{ t: 'SOUNDBOX_FIX' }, { t: 'DEFLECT' }] },
        },
        reply: 'Aapka Soundbox return scan mein mil gaya. Rent band kar diya aur ₹149 wapas kar diya.',
        win: true,
      }
    },
  },
  {
    id: 'noc', chip: 'Loan NOC', intent: 'LOAN_SETTLEMENT_NOC',
    utterance: () => 'Negotiated loan settlement bhar diya, NOC do',
    build(m) {
      const paid = Math.round((m.d.loan.balance * 0.7) / 100) * 100, noc = 'NOC-' + (100000 + Math.floor(Math.random() * 899999))
      return {
        purpose: 'loan_closure', scope: 'lending_ledger:write',
        payload: { topic: 'SETTLEMENT_NOC', paid_amount: paid },
        options: [opt('A', 'Ask merchant for payment proof', 28, 'Slow, payment is already in our ledger'), opt('B', 'Verify payment in lending ledger and auto-issue NOC', 95, 'Closes the loan instantly'), opt('C', 'Escalate to lending ops', 30, 'Unneeded delay')],
        selected: 'B',
        response: { status: 'LOAN_CLOSED_SETTLED', noc, paid_amount: paid },
        agents: {
          intelligence: { say: `Payment ${inr(paid)} matches negotiated settlement offer` },
          risk: { say: 'Payment cleared · no pending charges · EDI stopped' },
          resolution: { say: `Loan closed as SETTLED, NOC ${noc} generated` },
          ledger: { say: 'Lending ledger balance → ₹0', effects: [{ t: 'LOAN', status: 'NOC_ISSUED', balance: 0 }] },
        },
        reply: `Aapka ${inr(paid)} ka negotiated settlement mil gaya. Loan close ho gaya, NOC ${noc} Paytm app par bhej diya.`,
        win: true,
      }
    },
  },
  {
    id: 'bank', chip: 'Bank update', intent: 'KYC_BANK_UPDATE',
    utterance: () => 'Mera settlement bank account update karo',
    build(m) {
      const from = m.profile.bank_account, to = 'Axis ••6204'
      return {
        purpose: 'kyc_bank_update', scope: 'kyc_profile:write',
        payload: { topic: 'BANK_ACCOUNT_UPDATE', from, to },
        options: [opt('A', 'Update immediately, no verification', 10, 'High fraud / diversion risk'), opt('B', 'Penny-drop verify + owner-name match, then update', 96, 'Safe and instant'), opt('C', 'Human KYC branch visit', 36, 'Safe but slow')],
        selected: 'B',
        response: { status: 'BANK_UPDATED', to, effective: 'next settlement' },
        agents: {
          intelligence: { say: `Request: move settlements from ${from} to ${to}` },
          risk: { say: '₹1 penny-drop success · account holder name matches owner' },
          resolution: { say: 'Change approved, effective from next settlement' },
          ledger: { say: `Settlement account → ${to}`, effects: [{ t: 'BANK_UPDATE', to }] },
        },
        reply: `Naya bank account ${to} verify ho gaya (penny-drop). Agle settlement se paise isi mein aayenge.`,
        win: true,
      }
    },
  },
  {
    id: 'shield_cb', chip: 'Chargeback incoming', intent: 'CHARGEBACK_RESOLVE', proactive: 'CHARGEBACK_INCOMING',
    available: (m) => !!m.d.chargeback,
    utterance: (m) => `Paytm alert: chargeback incoming on order ${m.d.chargeback.order}`,
    build(m) {
      const c = m.d.chargeback, packet = 'DISPUTE-' + c.order.replace(/\D/g, '')
      return {
        purpose: 'proactive_chargeback_shield', scope: 'connector:shiprocket_sync:read',
        payload: { scenario: 'CHARGEBACK_INCOMING', order_id: c.order },
        options: [opt('A', 'Wait until the merchant notices', 14, 'Risk of missing the 48h deadline'), opt('B', 'Auto-pull PoD from consented Shiprocket, prepare dispute, ask 1-tap sign-off', 95, 'Nothing is sent without the merchant’s approval'), opt('C', 'Ask merchant to upload PoD manually', 52, 'Works, but slow and error-prone')],
        selected: 'B',
        response: { status: 'ALERT_RAISED', dispute_packet: { packet_id: packet, status: 'READY_FOR_SIGNOFF' }, awaiting_confirmation: 'CONFIRM_DISPUTE' },
        agents: {
          intelligence: { say: `Paytm webhook: dispute ${inr(c.amount)} on ${c.order}, 48h deadline` },
          risk: { say: 'SHIPROCKET_SYNC consent GRANTED · signed PoD pulled (stays on merchant side)' },
          resolution: { say: `Dispute packet ${packet} is READY_FOR_SIGNOFF` },
          ledger: { say: 'Waiting for merchant’s 1-tap sign-off · nothing sent to Paytm yet' },
        },
        reply: `${c.order} par ${inr(c.amount)} ka chargeback aaya hai. Shiprocket se delivery proof mil gaya, dispute taiyaar hai. Bhej doon?`,
        confirm: { kind: 'dispute', packet, label: 'Haan, delivery proof bhej do' },
        win: false,
      }
    },
  },
  {
    id: 'confirm_cb', hidden: true, intent: 'CHARGEBACK_RESOLVE',
    utterance: () => 'Haan, delivery proof bhej do',
    build(m, ctx) {
      const c = m.d.chargeback
      return {
        purpose: 'chargeback_resolution', scope: 'chargeback:write',
        payload: { order_id: c.order, txn_id: c.txn, pod_submitted: true, pod_source: 'SHIPROCKET_SYNC', packet_id: ctx.packet },
        options: [opt('A', 'Keep waiting', 10, 'Deadline risk'), opt('B', 'Submit signed dispute packet to Paytm', 97, 'Merchant approved'), opt('C', 'Escalate', 20, 'Not needed')],
        selected: 'B',
        response: { status: 'RELEASED', order_id: c.order, release_eta: 'T+1' },
        agents: {
          intelligence: { say: `Merchant signed off packet ${ctx.packet}` },
          risk: { say: 'Consent valid · PoD inside the 48h window' },
          resolution: { say: `Dispute won — release ${inr(c.amount)}`, effects: [{ t: 'CB_RELEASE' }] },
          ledger: { say: `Hold ${c.order} HELD → RELEASED (T+1)`, effects: [{ t: 'DEFLECT' }] },
        },
        reply: `Dispute bhej diya. ${inr(c.amount)} ka hold RELEASED — T+1 mein bank mein aa jayega.`,
        win: true,
      }
    },
  },
  {
    id: 'shield_edi', chip: 'Cashflow gap', intent: 'FEE_GST_LOAN', proactive: 'CASHFLOW_EDI_SWITCH',
    utterance: () => 'Paytm alert: high refund request, payout may fall short',
    build(m) {
      const net = m.d.settlement.net, edi = m.d.loan.edi
      const ov = m.mid === 'PAYTM_MERCH_8821' ? { refund: 3500, proj: 1200, stock: 4500 } : null
      const refund = ov?.refund ?? Math.round((net * 0.8) / 100) * 100
      const proj = ov?.proj ?? net - refund
      const stock = ov?.stock ?? Math.round((net * 0.7) / 100) * 100
      const short = stock - proj, saved = edi * 2
      return {
        purpose: 'proactive_cashflow_edi', scope: 'connector:vyapar_pos_sync:read',
        payload: { scenario: 'CASHFLOW_EDI_SWITCH', refund_request: refund },
        options: [opt('A', 'Do nothing', 20, 'Merchant may miss tomorrow’s stock payment'), opt('B', 'Offer 2-day EDI pause (KFS clause 4.2) with merchant consent', 94, 'Frees cash, no penalty'), opt('C', 'Suggest an emergency loan', 38, 'Adds debt for a 2-day gap')],
        selected: 'B',
        response: { status: 'ALERT_RAISED', projected_net_payout: proj, edi_pause_offer: { offer_id: 'EDIOFFER-0001', eligible: true, pause_days: 2, edi_saved_inr: saved }, awaiting_confirmation: 'CONFIRM_EDI_PAUSE' },
        agents: {
          intelligence: { say: `Refund request ${inr(refund)} → projected payout only ${inr(proj)}` },
          risk: { say: `Tomorrow’s stock payable ${inr(stock)} (Vyapar sync) → shortfall ${inr(short)}`, tone: 'warn' },
          resolution: { say: `KFS clause 4.2 allows a 2-day EDI pause → saves ${inr(saved)}` },
          ledger: { say: 'Offer EDIOFFER-0001 ready · waiting for merchant consent' },
        },
        reply: `Kal ${inr(refund)} ka refund jayega to payout sirf ${inr(proj)} bachega, jabki ${inr(stock)} ka stock dena hai. Loan EDI 2 din ke liye pause kar doon? ${inr(saved)} bachenge.`,
        confirm: { kind: 'edi', offer_id: 'EDIOFFER-0001', pause_days: 2, saved, label: `Haan, EDI 2 din pause karo` },
        win: false,
      }
    },
  },
  {
    id: 'confirm_edi', hidden: true, intent: 'FEE_GST_LOAN',
    utterance: () => 'Haan, EDI 2 din pause karo',
    build(m, ctx) {
      const saved = ctx.saved ?? m.d.loan.edi * 2
      return {
        purpose: 'edi_pause', scope: 'lending_ledger:write',
        payload: { offer_id: ctx.offer_id, pause_days: 2 },
        options: [opt('A', 'Skip', 10, 'Shortfall remains'), opt('B', 'Execute 2-day EDI pause and log KFS consent artifact', 97, 'Merchant approved'), opt('C', 'Escalate', 15, 'Not needed')],
        selected: 'B',
        response: { status: 'EDI_PAUSED', loan_edi_status: 'PAUSED_2_DAYS', edi_saved_inr: saved },
        agents: {
          intelligence: { say: `Merchant approved offer ${ctx.offer_id}` },
          risk: { say: 'Pause ≤ 2 days · KFS clause 4.2 consent artifact logged' },
          resolution: { say: 'EDI paused for 2 days' },
          ledger: { say: `EDI ACTIVE → PAUSED_2_DAYS · saved ${inr(saved)}`, effects: [{ t: 'LOAN', status: 'PAUSED', note: `Paused 2 days · saved ${inr(saved)}` }] },
        },
        reply: `EDI 2 din ke liye pause ho gaya. ${inr(saved)} bache, koi penalty nahi.`,
        win: true,
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
      key: 'reply', title: 'Reply to merchant', reply: b.reply, tone: b.tone, confirm: b.confirm, ms: 95,
      effects: b.win ? [{ t: 'OUTCOME' }, { t: 'LEARN', text: `${sc.intent}: option ${b.selected} reinforced` }] : [],
    },
  ]
  return { sc, utterance: ctx.utterance || sc.utterance(m), steps, reply: b.reply }
}

export function routeText(text) {
  const t = text.toLowerCase()
  const has = (...k) => k.some((x) => t.includes(x))
  if (has('noc', 'negotiated', 'loan settlement')) return 'noc'
  if (has('rent', '149')) return 'sbrent'
  if (has('kyc', 'hold pe', 'settlement hold')) return 'hold'
  if (has('account update', 'bank account', 'bank update', 'update karo')) return 'bank'
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
    hold: { amount: HOLD_AMT[m.mid] || 18500, status: 'HELD' },
    bank: { acct: m.profile.bank_account, status: 'ACTIVE' },
    soundbox: { status: 'BILLED_AFTER_RETURN', rent: 149 },
    refunds: [], tickets: [], itc: 0, verified: 0, learned: 0, learnedLog: [], deflected: 0, fraud: 0,
  }
}

export function applyEffects(L, effects = []) {
  let s = { ...L }
  for (const e of effects) {
    if (e.t === 'ITC') s.itc += e.amount
    if (e.t === 'CB_RELEASE' && s.chargeback) s.chargeback = { ...s.chargeback, status: 'RELEASED' }
    if (e.t === 'LOAN') s.loan = { ...s.loan, status: e.status, note: e.note, ...(e.balance !== undefined ? { balance: e.balance } : {}) }
    if (e.t === 'HOLD_RELEASE') s.hold = { ...s.hold, status: 'RELEASED' }
    if (e.t === 'SOUNDBOX_FIX') s.soundbox = { ...s.soundbox, status: 'REFUNDED' }
    if (e.t === 'BANK_UPDATE') s.bank = { acct: e.to, status: 'UPDATED' }
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
