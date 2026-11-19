// Turns a run (dispatch response + reply text) into a calm, scannable answer: status chip, headline, key facts, details.
import { inr } from './data.js'

const MONEY = new Set(['gross', 'net_bank_credit', 'variance', 'amount', 'amount_inr', 'outstanding', 'payable', 'edi_saved_inr', 'order_amount_inr', 'projected_net_payout', 'foreclosure_charge', 'refund', 'release'])
const LABEL = {
  gross: 'कुल बिक्री', net_bank_credit: 'बैंक में आया', variance: 'कुल कटौती', utr: 'UTR', utr_number: 'UTR', amount: 'रकम', amount_inr: 'रकम',
  payer_app: 'पेमेंट ऐप', order_id: 'ऑर्डर', outstanding: 'बाकी लोन', payable: 'भरना है', foreclosure_charge: 'क्लोज़र चार्ज', noc_eta_days: 'NOC (दिन)',
  pickup_ticket: 'टिकट', ticket: 'टिकट', release_eta: 'पैसा कब मिलेगा', edi_saved_inr: 'बचत', order_amount_inr: 'ऑर्डर रकम', projected_net_payout: 'कल का payout',
  duplicates_found: 'डुप्लिकेट', pickup_within_hours: 'पिकअप (घंटे)', eta_hours: 'समय (घंटे)', current_account: 'बैंक खाता', lender: 'लोन देने वाला', settlement_date: 'तारीख',
}
const ORDER = ['gross', 'variance', 'net_bank_credit', 'utr', 'utr_number', 'amount', 'amount_inr', 'payer_app', 'order_id', 'order_amount_inr', 'outstanding', 'foreclosure_charge', 'payable', 'noc_eta_days', 'release_eta', 'pickup_ticket', 'ticket', 'pickup_within_hours', 'projected_net_payout', 'edi_saved_inr', 'current_account', 'eta_hours']
const STATUS_HI = {
  PENDING: 'पेंडिंग', SUCCESS: 'सफल', RELEASED: 'छूट गया', RESOLVED: 'हल हो गया', RECONCILED: 'हिसाब मिल गया', PROCESSED: 'हो गया', NOT_FOUND_SUSPECTED_FAKE: 'नकली लगता है',
  ESCALATED: 'टीम को भेजा', RETURN_INITIATED: 'पिकअप तय', FORECLOSURE_QUOTE_READY: 'कोट तैयार', KYC_UPDATE_LINK_SENT: 'लिंक भेजा', NO_BANK_HOLD: 'कोई होल्ड नहीं',
  ACTION_REQUIRED: 'आपकी मंज़ूरी चाहिए', ALERT_RAISED: 'आपकी मंज़ूरी चाहिए', EDI_PAUSED: 'EDI रुका', REFUND_INITIATED: 'रिफंड शुरू',
}

function tone(status, fraud, escalated, awaiting) {
  if (fraud) return ['bad', 'नकली लगता है']
  if (awaiting) return ['warn', 'आपकी मंज़ूरी चाहिए']
  if (escalated) return ['info', 'टीम को भेजा']
  if (/PENDING|ACTION_REQUIRED|ALERT/.test(status || '')) return ['warn', STATUS_HI[status] || 'पेंडिंग']
  return ['ok', STATUS_HI[status] && !['SUCCESS'].includes(status) ? STATUS_HI[status] : 'हो गया']
}

export function summarize(run, reply) {
  if (!reply) return null
  const disp = run?.steps?.find((s) => s.key === 'dispatch')
  const res = disp?.response || {}
  const data = res.data && typeof res.data === 'object' ? res.data : res
  const status = res.status || data.status
  const fraud = status === 'NOT_FOUND_SUSPECTED_FAKE' || reply.tone === 'bad'
  const [kind, chip] = tone(status, fraud, run?.live ? run.escalated : run?.sc?.intent === 'ESCALATE_HUMAN' || !!res.ticket, !!reply.confirm)

  const facts = []
  const keys = [...ORDER.filter((k) => k in data), ...Object.keys(data).filter((k) => !ORDER.includes(k))]
  for (const k of keys) {
    const v = data[k]
    if (facts.length >= 4) break
    if (v === null || v === undefined || typeof v === 'object' || !LABEL[k]) continue
    if (typeof v === 'string' && v.length > 28) continue
    facts.push({ k: LABEL[k], v: MONEY.has(k) && typeof v === 'number' ? inr(v) : typeof v === 'string' && STATUS_HI[v] ? STATUS_HI[v] : String(v) })
  }

  const parts = reply.text.split(/(?<=[.।!?])\s+/).filter(Boolean)
  return { kind, chip, headline: parts[0] || reply.text, detail: parts.slice(1).join(' '), facts }
}
