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

const AMT = /₹\s?[\d,]+(?:\.\d+)?/g
const tidy = (s) => s.replace(/\s+/g, ' ').replace(/^[\s,;:—-]+|[\s,;:—.-]+$/g, '').replace(/\s+(hai|है|hain)$/i, '')
function breakdown(sentence, lang) {
  let main = sentence, tail = ''
  const dash = main.split(/\s+[—–]\s+/)
  if (dash.length > 1) { main = dash[0]; tail = dash.slice(1).join(' — ') }
  let intro = '', list = main
  const colon = main.match(/^([^:]{3,90}):\s*(.+)$/)
  if (colon) { intro = colon[1]; list = colon[2] }
  const chunks = list.split(/\s*;\s*|,\s+(?:and\s+|aur\s+|और\s+)?|\s+(?:aur|and|और)\s+/).map((x) => x.trim()).filter(Boolean)
  if (chunks.filter((x) => (x.match(AMT) || []).length >= 1).length < 3) return null
  const first = chunks[0].match(AMT) || []
  if (!colon && first.length >= 2) { // "₹4,160 mein MDR ₹1,450, GST …": the first amount is the total
    const i = chunks[0].indexOf(first[0]) + first[0].length
    intro = chunks[0].slice(0, i); chunks[0] = chunks[0].slice(i).replace(/^\s*(mein|में|is|was|are|of)\s+/i, '')
    if (!/[A-Za-z\u0900-\u097F]/.test(intro.replace(first[0], ''))) intro = lang === 'en' ? `${first[0]} was deducted` : lang === 'hi' ? `${first[0]} कटे` : `${first[0]} kate`
  }
  const items = []
  for (const ch of chunks) {
    const m = ch.match(/^(.*?)\s*(₹\s?[\d,]+(?:\.\d+)?)\s*(.*)$/)
    if (!m) { if (items.length && !/[₹]/.test(ch)) continue; return null }
    let before = m[1], after = m[3].replace(/\s+(hai|है|hain)\s*$/i, '')
    const ref = before.match(/^(#?[\w-]+)\s+(ka|ki|ke|of|for|का|की|के)$/i)
    if (ref) { before = ''; after = `${after} (${ref[1]})` }
    let label = tidy(`${before} ${after}`).replace(/^(a|an|the|and|aur|और)\s+/i, '')
    if (!label) continue
    items.push({ k: label.charAt(0).toUpperCase() + label.slice(1), v: m[2].replace(/\s/g, '') })
  }
  if (items.length < 3) return null
  return { intro: tidy(intro) || sentence, items, tail: tail ? tidy(tail) + '.' : '' }
}

export function summarize(run, reply, lang = 'hi') {
  if (!reply) return null
  const disp = run?.steps?.find((s) => s.key === 'dispatch')
  const res = disp?.response || {}
  const data = res.data && typeof res.data === 'object' ? res.data : res
  const status = res.status || data.status
  const fraud = status === 'NOT_FOUND_SUSPECTED_FAKE' || reply.tone === 'bad'
  const [kind, chip] = run?.unclear ? ['warn', t(lang, 'cUnclear')] // not "Done": the buddy asked to rephrase
    : run?.info ? ['ok', t(lang, 'cBooks')]
    : tone(lang, status, fraud, run?.live ? run.escalated : run?.sc?.intent === 'ESCALATE_HUMAN' || !!res.ticket, !!reply.confirm)

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
  // A sentence that lists 3+ "label ₹amount" items (using : ; , and/aur) becomes a short headline + one clean row per item.
  let headline = parts[0] || reply.text
  let rest = parts.slice(1)
  let factsTitle = '', context = ''
  for (let j = 0; j < parts.length; j++) {
    const bd = breakdown(parts[j], lang)
    if (!bd) continue
    facts.length = 0; facts.push(...bd.items)
    if (j === 0) { headline = bd.intro; rest = parts.slice(1) } else { context = parts[0]; headline = bd.intro + ':'; rest = parts.filter((_, k) => k !== 0 && k !== j) }
    if (bd.tail) rest = [bd.tail, ...rest]
    break
  }
  const detail = rest.join(' ')
  return { kind, chip, headline, context, factsTitle, detail, facts }
}
