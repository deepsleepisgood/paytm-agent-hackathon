// Local A2A simulation: Merchant Buddy -> Paytm 4-agent mesh. Deterministic so the demo never breaks
// when backends (8001-8003) are offline. Replace `runScenario` with real /merchant/query calls when ready.
import { inr } from './data.js'

const hex = (n) => Math.random().toString(16).slice(2, 2 + n)
const rid = () => 'req_' + hex(8)
const tkt = () => 'TKT-PAYTM-' + (1000 + Math.floor(Math.random() * 9000))
const ded = (m, code) => m.d.settlement.deductions.find((x) => x.key === code)?.amount || 0
const REFUND_ASK = { PAYTM_MERCH_8821: 6500 }
const FAKE_UTR = '632184929999'
const DUP_AMT = { PAYTM_MERCH_8821: 3200 }
const HOLD_AMT = { PAYTM_MERCH_8821: 18500 }

const opt = (id, label, score, why) => ({ id, label, score, why })

// Mirrors services/merchant_agent/schemas.py Intent (14 names, incl. the original 6 and the 4 service requests).
export const CONTRACT_INTENTS = ['SETTLEMENT_RECONCILE', 'UTR_VERIFY', 'CHARGEBACK_RESOLVE', 'REFUND_MANAGE', 'FEE_GST_LOAN', 'ESCALATE_HUMAN', 'MANDATE_TROUBLESHOOT', 'DUPLICATE_RECONCILE', 'GROWTH_ADVISORY', 'CASHFLOW_EDI_SWITCH', 'SOUNDBOX_RETURN', 'LOAN_CLOSURE_NOC', 'BANK_KYC_UPDATE', 'SETTLEMENT_HOLD_BANK']
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
        replies: { hi: `${inr(s.variance)} kate: MDR ${inr(ded(m, 'MDR_FEE'))}, GST ${inr(gst)}, refund ${inr(ded(m, 'CUSTOMER_REFUND'))}, Soundbox ₹149${cb ? `, aur ${inr(cb.amount)} ka chargeback hold (${cb.order})` : ''}.${cb ? ' Delivery ka proof bhejiye, hold hat jayega.' : ''}`, en: `${inr(s.variance)} was deducted: MDR ${inr(ded(m, 'MDR_FEE'))}, GST ${inr(gst)}, refund ${inr(ded(m, 'CUSTOMER_REFUND'))}, Soundbox ₹149${cb ? `, and a ${inr(cb.amount)} chargeback hold (${cb.order})` : ''}.${cb ? ' Send the delivery proof and the hold will be released.' : ''}` },
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
        replies: { hi: `UTR ${t.utr}: ${inr(t.amount)} (${t.app}) abhi pending hai. NPCI T+1 tak settle ya auto-reverse kar dega. Tab tak saman mat dijiye.`, en: `UTR ${t.utr}: ${inr(t.amount)} (${t.app}) is still pending. NPCI will settle or auto-reverse it by T+1. Do not hand over goods until then.` },
        win: true,
      }
    },
  },
  {
    id: 'dup', chip: 'Duplicate payment', intent: 'DUPLICATE_RECONCILE',
    utterance: (m) => `PhonePe se ${inr(DUP_AMT[m.mid] || 1180)} do baar kat gaya`,
    build(m) {
      const amt = DUP_AMT[m.mid] || 1180, order = '#4455'
      return {
        purpose: 'duplicate_payment', scope: 'upi_ledger:read',
        payload: { topic: 'DUPLICATE_PAYMENT', amount: amt },
        options: [opt('A', 'Ask the customer to claim from their bank', 20, 'Customer is left waiting'), opt('B', 'Match both UTRs to one order and refund the second payment', 94, 'Fast, merchant keeps the customer'), opt('C', 'Escalate to a human', 30, 'Not needed')],
        selected: 'B',
        response: { status: 'RESOLVED', duplicates_found: 1, order_id: order, order_amount_inr: amt, refund: { status: 'PROCESSED', amount: amt } },
        agents: {
          intelligence: { say: `Order ${order} has two successful payments of ${inr(amt)}` },
          risk: { say: 'Both UTRs settled · same order · duplicate confirmed' },
          resolution: { say: 'Refund the second payment' },
          ledger: { say: `Refund ${inr(amt)} processed · order reconciled to one payment`, effects: [{ t: 'REFUND_AUTO', order, amount: amt }, { t: 'DEFLECT' }] },
        },
        reply: `Order ${order} ke ${inr(amt)} do baar kate. Duplicate payment ka refund shuru kar diya, T+1 mein pahunch jayega.`,
        replies: { hi: `Order ${order} ke ${inr(amt)} do baar kate. Doosre payment ka refund shuru kar diya, T+1 mein pahunch jayega.`, en: `Order ${order} was charged ${inr(amt)} twice. I started a refund for the second payment; it arrives by T+1.` },
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
        replies: { hi: `Dhyan dijiye! Yeh UTR aapke Paytm account mein nahi hai. Jab tak paisa na dikhe, saman mat dijiye.`, en: `Warning! This UTR is not in our ledger — the screenshot looks fake. Do not hand over the goods!` },
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
        replies: { hi: `Delivery ka proof mil gaya (order ${c.order}). ${inr(c.amount)} ka hold chhoot gaya — T+1 mein bank mein aa jayega.`, en: `Delivery proof received (order ${c.order}). The ${inr(c.amount)} hold is released and reaches your bank by T+1.` },
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
        replies: { hi: auto ? `${inr(amt)} ka refund shuru kar diya (${order}). Customer ko 1–2 din mein mil jayega.` : `${inr(amt)} ₹5,000 se upar hai, isliye L2 ticket ${id} bana diya. Team jaldi approve karegi.`, en: auto ? `Refund of ${inr(amt)} started (${order}). The customer gets it in 1–2 days.` : `${inr(amt)} is above ₹5,000, so I created L2 ticket ${id}. The team will approve it soon.` },
        win: auto,
      }
    },
  },
  {
    id: 'edi', chip: 'Loan EDI fail', intent: 'MANDATE_TROUBLESHOOT',
    utterance: (m) => `Mera ${inr(m.d.loan.edi)} ka loan EDI mandate fail ho gaya`,
    build(m) {
      const e = m.d.loan.edi
      return {
        purpose: 'loan_edi_support', scope: 'lending_ledger:write',
        payload: { topic: 'EDI_MANDATE_FAIL', edi_per_day: e },
        insight: { summary: 'Friction, not default: sales dipped for a few days, but 96% of EDIs were paid on time in 6 months', evidence: [`eNACH bounce: INSUFFICIENT_FUNDS (${inr(e)})`, '96% EDIs on time over 6 months', 'Sales recovered the next day'] },
        options: [opt('A', 'Send a reminder and retry the eNACH debit', 28, 'Slow, low past success'), opt('B', '1-tap UPI link for the missed EDI + 48h grace, penalty waived', 77, 'Best past success, best experience'), opt('C', 'Escalate to a specialist', 35, 'Not needed for a first bounce')],
        selected: 'B',
        response: { status: 'ACTION_REQUIRED', action_required: { type: 'CHOOSE_REMEDY', options: ['PAY_NOW_UPI_LINK', 'KFS_HARDSHIP_PAUSE'], amount_inr: e } },
        agents: {
          intelligence: { say: `Read mandate: ${inr(e)} bounced (INSUFFICIENT_FUNDS); 96% on time over 6 months` },
          risk: { say: 'Bounced once with 96% on time: not a default, and a 2-day pause is available under KFS 4.2', tone: 'warn' },
          resolution: { say: 'Explained it is not a default, and offered a UPI link or a 2-day pause' },
          ledger: { say: 'Mandate flagged · UPI link sent', effects: [{ t: 'LOAN', status: 'LINK_SENT', note: `${inr(e)} bounced · 1-tap UPI link sent · penalty waived` }] },
        },
        reply: `Aapka ${inr(e)} ka EDI fail hua, ye default nahi hai. 1-tap UPI link bhej diya hai, penalty nahi lagegi.`,
        replies: { hi: `Aapki ${inr(e)} ki EDI fail hui thi — yeh default nahi hai. 1-tap UPI link bhej diya hai, penalty nahi lagegi.`, en: `Your ${inr(e)} EDI failed — this is not a default. I sent a 1-tap UPI link and no penalty will apply.` },
        win: true,
      }
    },
  },
  {
    id: 'growth', chip: 'Business badhao', intent: 'GROWTH_ADVISORY',
    utterance: () => 'Mere pichle 6 mahine ke data se business badhane ka suggestion do',
    build(m) {
      const i = m.insights, ms = i.monthly_sales, pct = Math.round(((ms[ms.length - 1] - ms[0]) / ms[0]) * 100)
      const [g1, g2] = i.growth_suggestions
      return {
        purpose: 'business_insights', scope: 'sales_history:read',
        payload: { topic: 'GROWTH_SUGGESTION', period: i.period },
        insight: { summary: i.peak_note, evidence: [`6-month sales ${pct >= 0 ? '+' : ''}${pct}%`, i.cashflow_health.note, ...i.growth_suggestions.slice(0, 2).map((g) => g.title)] },
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
        replies: { hi: `Pichhle 6 mahine mein sale ${pct}% badhi. ${g1.hinglish || g1.hi} Saath mein: ${g2.hinglish || g2.hi}`, en: `Sales grew ${pct}% in the last 6 months. ${g1.en || g1.title} Also: ${g2.en || g2.title}` },
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
        replies: { hi: `Soundbox mein hardware ki dikkat lag rahi hai. L2 ticket ${id} bana diya, engineer 24 ghante mein contact karega.`, en: `This looks like a Soundbox hardware fault. I created L2 ticket ${id}; an engineer will contact you within 24 hours.` },
        win: false,
      }
    },
  },
  {
    id: 'hold', chip: 'Settlement hold', intent: 'SETTLEMENT_HOLD_BANK',
    utterance: (m) => `Mera ${inr(HOLD_AMT[m.mid] || 18500)} settlement bank/KYC hold pe kyun hai?`,
    build(m) {
      const cb = m.d.chargeback, net = m.d.settlement.net, acct = m.profile.bank_account
      return {
        purpose: 'settlement_hold_review', scope: 'settlement_ledger:read',
        payload: { topic: 'SETTLEMENT_HOLD' },
        options: [opt('A', 'Tell the merchant to wait for the bank', 22, 'Gives no answer'), opt('B', 'Check bank + KYC status and explain any open holds', 90, 'Answers with facts from the ledger'), opt('C', 'Escalate to compliance', 30, 'Slow, nothing is actually blocked')],
        selected: 'B',
        response: { status: 'NO_BANK_HOLD', bank_status: 'ACTIVE', kyc_status: 'VERIFIED', open_holds: cb ? [{ order_id: cb.order, amount: cb.amount, type: 'CHARGEBACK_HOLD' }] : [] },
        agents: {
          intelligence: { say: `Bank ${acct} ACTIVE · KYC VERIFIED · last credit ${inr(net)}` },
          risk: { say: 'No bank or KYC hold on this account' },
          resolution: { say: cb ? `Only open hold: ${cb.order} chargeback, ${inr(cb.amount)}` : 'No open holds' },
          ledger: { say: 'No ledger change required' },
        },
        reply: `Aapka bank account ACTIVE hai, koi bank hold nahi; ${inr(net)} credit ho chuka hai.${cb ? ` Sirf ${cb.order} ka ${inr(cb.amount)} chargeback hold hai.` : ''}`,
        replies: { hi: `Aapka bank account chalu hai, koi bank hold nahi; ${inr(net)} jama ho chuka hai.${cb ? ` Sirf ${cb.order} ka ${inr(cb.amount)} chargeback hold hai.` : ''}`, en: `Your bank account is active with no bank hold; ${inr(net)} has been credited.${cb ? ` Only ${cb.order} has a ${inr(cb.amount)} chargeback hold.` : ''}` },
        win: true,
      }
    },
  },
  {
    id: 'sbrent', chip: 'Soundbox rent', intent: 'SOUNDBOX_RETURN',
    utterance: () => 'Soundbox wapas kar diya phir bhi ₹149 rent kat raha hai',
    build() {
      const ticket = 'PICKUP-' + (1000 + Math.floor(Math.random() * 9000))
      return {
        purpose: 'device_return', scope: 'device_billing:write',
        payload: { topic: 'SOUNDBOX_RETURN', monthly_rental: 149 },
        options: [opt('A', 'Ask the merchant for a return receipt', 30, 'Slow, adds a step'), opt('B', 'Schedule pickup, stop rental from next cycle, pro-rata final bill', 93, 'Fixes billing without paperwork'), opt('C', 'Escalate to a human', 26, 'Not needed')],
        selected: 'B',
        response: { status: 'RETURN_INITIATED', pickup_ticket: ticket, pickup_within_hours: 48, rental_stops: 'from next billing cycle', final_charge: 'pro-rata' },
        agents: {
          intelligence: { say: 'Soundbox on ₹149/month rental, return requested' },
          risk: { say: 'Return eligible · final bill will be pro-rata' },
          resolution: { say: `Pickup scheduled within 48h (${ticket})` },
          ledger: { say: 'Rental stops from the next billing cycle', effects: [{ t: 'SOUNDBOX_FIX', note: ticket }] },
        },
        reply: `Soundbox ki pickup 48 ghante mein hogi, ticket ${ticket}. ₹149 ka rental agle cycle se band ho jayega, aakhri bill pro-rata katega.`,
        replies: { hi: `Soundbox ki pickup 48 ghante mein hogi, ticket ${ticket}. ₹149 ka rent agle cycle se band ho jayega, aakhri bill pro-rata katega.`, en: `Soundbox pickup will happen within 48 hours, ticket ${ticket}. The ₹149 rent stops from the next cycle and the final bill is pro-rata.` },
        win: true,
      }
    },
  },
  {
    id: 'noc', chip: 'Loan NOC', intent: 'LOAN_CLOSURE_NOC',
    utterance: () => 'Negotiated loan settlement bhar diya, NOC do',
    build(m) {
      const bal = m.d.loan.balance, lender = m.d.loan.lender || 'Clix Capital'
      return {
        purpose: 'loan_closure', scope: 'lending_ledger:read',
        payload: { topic: 'LOAN_CLOSURE_NOC' },
        options: [opt('A', 'Ask the merchant for payment proof', 25, 'Slow, our ledger already knows'), opt('B', 'Check the lending ledger and issue a foreclosure quote with NOC timeline', 94, 'Clear next step for the merchant'), opt('C', 'Escalate to lending ops', 30, 'Unneeded delay')],
        selected: 'B',
        response: { status: 'FORECLOSURE_QUOTE_READY', lender, outstanding: bal, foreclosure_charge: 0, payable: bal, noc_eta_days: 7 },
        agents: {
          intelligence: { say: `${lender}: outstanding ${inr(bal)}, foreclosure charge ₹0` },
          risk: { say: 'No pending penalties · EDI history 96% on time' },
          resolution: { say: 'Foreclosure quote ready · NOC within 7 days of payment' },
          ledger: { say: 'Quote saved to the lending ledger', effects: [{ t: 'LOAN', status: 'QUOTE', note: `Pay ${inr(bal)} to close · NOC in 7 days` }] },
        },
        reply: `${lender} loan ka baaki ${inr(bal)} hai, foreclosure charge ₹0. Bhugtan ke 7 din mein NOC mil jayega.`,
        replies: { hi: `${lender} loan ka baaki ${inr(bal)} hai, closure charge ₹0. Payment ke 7 din mein NOC mil jayega.`, en: `Your ${lender} loan balance is ${inr(bal)} with ₹0 closure charge. You get the NOC within 7 days of payment.` },
        win: true,
      }
    },
  },
  {
    id: 'bank', chip: 'Bank update', intent: 'BANK_KYC_UPDATE',
    utterance: () => 'Mera settlement bank account update karo',
    build(m) {
      const from = m.profile.bank_account
      return {
        purpose: 'kyc_bank_update', scope: 'kyc_profile:write',
        payload: { topic: 'BANK_ACCOUNT_UPDATE', from },
        options: [opt('A', 'Change the account immediately', 8, 'High fraud / diversion risk'), opt('B', 'Send a secure link, verify with ₹1 penny-drop first', 96, 'Safe and fully digital'), opt('C', 'Ask for a branch visit', 34, 'Safe but slow')],
        selected: 'B',
        response: { status: 'KYC_UPDATE_LINK_SENT', current_account: from, verification: 'PENNY_DROP', eta_hours: '24-48' },
        agents: {
          intelligence: { say: `Request: move settlements away from ${from}` },
          risk: { say: 'Needs a ₹1 penny-drop and owner-name match first' },
          resolution: { say: 'Secure link sent · settlements stay on the old account until verified' },
          ledger: { say: 'Account change pending verification', effects: [{ t: 'BANK_UPDATE' }] },
        },
        reply: 'Naya bank account jodne ka secure link bhej diya hai. Penny-drop verify hote hi 24-48 ghante mein settlement naye account mein aayega, tab tak purane mein aayega.',
        replies: { hi: `Naya bank account jodne ka secure link bhej diya hai. Penny-drop verify hote hi 24-48 ghante mein settlement naye account mein aayega, tab tak purane mein aayega.`, en: `I sent a secure link to add the new bank account. Once the ₹1 penny-drop verifies, settlements move to it within 24–48 hours; until then they go to the old account.` },
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
        replies: { hi: `${c.order} par ${inr(c.amount)} ka chargeback aaya hai. Shiprocket se delivery ka proof mil gaya, dispute taiyaar hai. Bhej doon?`, en: `A ${inr(c.amount)} chargeback arrived on ${c.order}. I found the delivery proof in Shiprocket and the dispute is ready. Shall I send it?` },
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
        replies: { hi: `Dispute bhej diya. ${inr(c.amount)} ka hold chhoot gaya — T+1 mein bank mein aa jayega.`, en: `Dispute sent. The ${inr(c.amount)} hold is released and reaches your bank by T+1.` },
        win: true,
      }
    },
  },
  {
    id: 'shield_edi', chip: 'Cashflow gap', intent: 'CASHFLOW_EDI_SWITCH', proactive: 'CASHFLOW_EDI_SWITCH',
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
        replies: { hi: `Kal ${inr(refund)} ka refund jayega toh payout sirf ${inr(proj)} bachega, jabki ${inr(stock)} ka stock dena hai. Loan EDI 2 din ke liye rok doon? ${inr(saved)} bachenge.`, en: `After tomorrow's ${inr(refund)} refund your payout is only ${inr(proj)}, but ${inr(stock)} is due for stock. Pause the loan EDI for 2 days? You save ${inr(saved)}.` },
        win: false,
      }
    },
  },
  {
    id: 'confirm_edi', hidden: true, intent: 'CASHFLOW_EDI_SWITCH',
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
        replies: { hi: `EDI 2 din ke liye ruk gaya. ${inr(saved)} bache, koi penalty nahi.`, en: `EDI paused for 2 days. You save ${inr(saved)} with no penalty.` },
        win: true,
      }
    },
  },
]


// What the merchant says, shown as their own words in each language. (Live mode still sends the backend-tested phrase.)
const SAY = {
  settle: { hi: (m) => `Kal ₹${m.d.settlement.gross.toLocaleString('en-IN')} ki sale thi, bank mein ${inr(m.d.settlement.net)} aaye — ${inr(m.d.settlement.variance)} kahan kate?`, en: (m) => `Yesterday's sales were ₹${m.d.settlement.gross.toLocaleString('en-IN')} but the bank got ${inr(m.d.settlement.net)} — where was ${inr(m.d.settlement.variance)} deducted?` },
  utr: { hi: (m) => `UTR ${m.d.transactions.find((t) => t.status === 'PENDING').utr} ka payment check karo`, en: (m) => `Check the payment for UTR ${m.d.transactions.find((t) => t.status === 'PENDING').utr}` },
  dup: { hi: (m) => `PhonePe se ${inr(DUP_AMT[m.mid] || 1180)} do baar kat gaya`, en: (m) => `${inr(DUP_AMT[m.mid] || 1180)} was charged twice on PhonePe` },
  fake: { hi: () => 'Customer ne yeh screenshot dikhaya, paisa aaya ya nahi?', en: () => 'The customer showed this screenshot — did the money arrive?' },
  cb: { hi: (m) => `Haan, delivery ka proof bhejo (order ${m.d.chargeback.order})`, en: (m) => `Yes, send the delivery proof (order ${m.d.chargeback.order})` },
  refund: { hi: (m) => `Customer ko ${inr(REFUND_ASK[m.mid] || 6500)} wapas karna hai`, en: (m) => `I need to refund ${inr(REFUND_ASK[m.mid] || 6500)} to a customer` },
  edi: { hi: (m) => `Meri ${inr(m.d.loan.edi)} ki loan EDI fail ho gayi`, en: (m) => `My ${inr(m.d.loan.edi)} loan EDI failed` },
  growth: { hi: () => 'Mere pichhle 6 mahine ke data se business badhane ka suggestion do', en: () => 'Based on my last 6 months of data, tell me how to grow my business' },
  soundbox: { hi: () => 'Soundbox bol nahi raha, kaam nahi kar raha', en: () => 'My Soundbox is not speaking or working' },
  hold: { hi: (m) => `Mera ${inr(HOLD_AMT[m.mid] || 18500)} ka settlement bank/KYC hold par kyon hai?`, en: (m) => `Why is my ${inr(HOLD_AMT[m.mid] || 18500)} settlement on bank/KYC hold?` },
  sbrent: { hi: () => 'Soundbox wapas kar diya phir bhi ₹149 rent kat raha hai', en: () => 'I returned the Soundbox but ₹149 rent is still being charged' },
  noc: { hi: () => 'Negotiated loan settlement bhar diya, NOC dijiye', en: () => 'I paid the negotiated loan settlement — please give me the NOC' },
  bank: { hi: () => 'Mera settlement bank account badal do', en: () => 'Please change my settlement bank account' },
  shield_cb: { hi: (m) => `Paytm alert: order ${m.d.chargeback.order} par chargeback aaya hai`, en: (m) => `Paytm alert: chargeback received on order ${m.d.chargeback.order}` },
  shield_edi: { hi: () => 'Paytm alert: bada refund, payout kam pad sakta hai', en: () => 'Paytm alert: large refund, payout may fall short' },
  confirm_cb: { hi: () => 'Haan, delivery ka proof bhej do', en: () => 'Yes, send the delivery proof' },
  confirm_edi: { hi: () => 'Haan, EDI 2 din rok do', en: () => 'Yes, pause EDI for 2 days' },
}
export const sayText = (sc, m, lang = 'hi') => (SAY[sc.id] && SAY[sc.id][lang] ? SAY[sc.id][lang](m) : sc.utterance(m))
export const CONFIRM_LABEL = { dispute: { hi: 'Haan, delivery ka proof bhej do', en: 'Yes, send the delivery proof' }, edi: { hi: 'Haan, EDI 2 din rok do', en: 'Yes, pause EDI for 2 days' } }

export function runScenario(sc, m, ctx = {}) {
  const lang = ctx.lang || 'hi'
  const b = sc.build(m, ctx)
  const reply = (b.replies && b.replies[lang]) || b.reply
  if (b.confirm) b.confirm = { ...b.confirm, label: CONFIRM_LABEL[b.confirm.kind][lang] }
  const consent = { token: 'cns_' + hex(12), purpose: b.purpose, scope: b.scope, ttl_min: 15, issued: new Date().toISOString().slice(11, 19) + 'Z', mid: m.mid }
  const request = { request_id: rid(), mid: m.mid, intent: sc.intent, payload: b.payload, consent_token: consent.token }
  const A = b.agents
  const steps = [
    { key: 'input', title: 'Input understood', say: `intent=${sc.intent} · lang=hi-IN`, ms: 120 },
    { key: 'consent', title: 'DPDP consent', consent, ms: 90 },
    ...(b.insight ? [{ key: 'insight', title: 'What the AI knew', insight: b.insight, ms: 60 }] : []),
    { key: 'eval', title: 'Intervention evaluation', options: b.options, selected: b.selected, ms: 340 },
    { key: 'dispatch', title: 'A2A dispatch', request, response: b.response, ms: 210 },
    { key: 'intelligence', title: 'Intelligence', ...A.intelligence, ms: 260 },
    { key: 'risk', title: 'Risk', ...A.risk, ms: 180 },
    { key: 'resolution', title: 'Resolution', ...A.resolution, ms: 310 },
    { key: 'ledger', title: 'Ledger Ops', ...A.ledger, ms: 150 },
    {
      key: 'reply', title: 'Reply to merchant', reply, replies: b.replies, tone: b.tone, confirm: b.confirm, ms: 95,
      effects: b.win ? [{ t: 'OUTCOME' }, { t: 'LEARN', text: `${sc.intent}: option ${b.selected} reinforced` }] : [],
    },
  ]
  return { sc, utterance: ctx.utterance || sayText(sc, m, lang), steps, reply }
}

export function routeText(text) {
  const t = text.toLowerCase()
  const has = (...k) => k.some((x) => t.includes(x))
  if (has('do baar', 'double', 'duplicate', 'twice')) return 'dup'
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
    hold: { amount: 0, status: 'NONE' },
    bank: { acct: m.profile.bank_account, status: 'ACTIVE' },
    soundbox: { status: 'ACTIVE', rent: 149 },
    refunds: [], tickets: [], itc: 0, verified: 0, learned: 0, learnedLog: [], deflected: 0, fraud: 0,
  }
}

export function applyEffects(L, effects = []) {
  let s = { ...L }
  for (const e of effects) {
    if (e.t === 'ITC') s.itc += e.amount
    if (e.t === 'CB_RELEASE' && s.chargeback) s.chargeback = { ...s.chargeback, status: 'RELEASED' }
    if (e.t === 'LOAN') s.loan = { ...s.loan, status: e.status, note: e.note, ...(e.balance !== undefined ? { balance: e.balance } : {}) }
    if (e.t === 'SOUNDBOX_FIX') s.soundbox = { ...s.soundbox, status: 'PICKUP', note: e.note }
    if (e.t === 'BANK_UPDATE') s.bank = { ...s.bank, status: 'LINK_SENT' }
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
