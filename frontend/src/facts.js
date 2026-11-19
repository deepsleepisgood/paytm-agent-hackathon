// Turns a run (dispatch response + reply text) into a calm, scannable answer: status chip, headline, key facts, details.
import { inr } from './data.js'

const MONEY = new Set(['gross', 'net_bank_credit', 'variance', 'amount', 'amount_inr', 'outstanding', 'payable', 'edi_saved_inr', 'order_amount_inr', 'projected_net_payout', 'foreclosure_charge', 'refund', 'release'])
import { FACT, STATUS, t } from './i18n.js'

const ORDER = ['gross', 'variance', 'net_bank_credit', 'utr', 'utr_number', 'amount', 'amount_inr', 'payer_app', 'order_id', 'order_amount_inr', 'outstanding', 'foreclosure_charge', 'payable', 'noc_eta_days', 'release_eta', 'pickup_ticket', 'ticket', 'pickup_within_hours', 'projected_net_payout', 'edi_saved_inr', 'current_account', 'eta_hours']

function tone(lang, status, fraud, escalated, awaiting) {
  if (fraud) return ['bad', t(lang, 'cFake')]
  if (awaiting) return ['warn', t(lang, 'cWait')]
  if (escalated) return ['info', t(lang, 'cTeam')]
  if (/PENDING|ACTION_REQUIRED|ALERT/.test(status || '')) return ['warn', STATUS[lang][status] || t(lang, 'cPend')]
  return ['ok', STATUS[lang][status] && !['SUCCESS'].includes(status) ? STATUS[lang][status] : t(lang, 'cHold')]
}

export function summarize(run, reply, lang = 'hi') {
  if (!reply) return null
  const disp = run?.steps?.find((s) => s.key === 'dispatch')
  const res = disp?.response || {}
  const data = res.data && typeof res.data === 'object' ? res.data : res
  const status = res.status || data.status
  const fraud = status === 'NOT_FOUND_SUSPECTED_FAKE' || reply.tone === 'bad'
  const [kind, chip] = tone(lang, status, fraud, run?.live ? run.escalated : run?.sc?.intent === 'ESCALATE_HUMAN' || !!res.ticket, !!reply.confirm)

  const facts = []
  const keys = [...ORDER.filter((k) => k in data), ...Object.keys(data).filter((k) => !ORDER.includes(k))]
  for (const k of keys) {
    const v = data[k]
    if (facts.length >= 4) break
    if (v === null || v === undefined || typeof v === 'object' || !FACT[lang][k]) continue
    if (typeof v === 'string' && v.length > 28) continue
    facts.push({ k: FACT[lang][k], v: MONEY.has(k) && typeof v === 'number' ? inr(v) : typeof v === 'string' && STATUS[lang][v] ? STATUS[lang][v] : String(v) })
  }

  const parts = reply.text.split(/(?<=[.।!?])\s+/).filter(Boolean)
  return { kind, chip, headline: parts[0] || reply.text, detail: parts.slice(1).join(' '), facts }
}
