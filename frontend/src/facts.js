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
// Plain words an SME owner uses, no order numbers or jargon.
const SIMPLE = [
  [/chargeback|dispute|held|hold/i, 'On hold (customer dispute)'],
  [/refund/i, 'Customer refund'],
  [/soundbox/i, 'Soundbox rent'],
  [/gst/i, 'GST on fees'],
  [/mdr|payment fee|processing|fee/i, 'Payment fees'],
]
const simpleLabel = (l) => { for (const [re, out] of SIMPLE) if (re.test(l)) return out; return l.replace(/\s*(for|on)?\s*order\s*#?\d+/i, '').replace(/\s*\(#?\d+\)/, '').trim() }
const needsYou = /\?|\b(send|share|upload|confirm|approve|tap|reply|provide|please|bhejiye|bhejo|batao|bataiye|dijiye|kijiye|rakhiye|bhariye|mat|link|callback|कीजिए|भेजिए)\b/i
const isHinglish = (s) => /\b(hai|hain|mein|aur|kiya|kijiye|bhejiye|dijiye|nahi|aapke|aapka|ka|ki|ko)\b/i.test(s)
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
    label = simpleLabel(label)
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
  let usedBreakdown = false
  for (let j = 0; j < parts.length; j++) {
    const bd = breakdown(parts[j], lang)
    if (!bd) continue
    usedBreakdown = true
    facts.length = 0; facts.push(...bd.items)
    const amt = (bd.intro.match(AMT) || [])[0]
    const cut = amt && /differ|deduct|kate|कटे|cut|less/i.test(bd.intro)
    headline = cut ? (isHinglish(parts[j]) ? `${amt} aapke payout se kate` : lang === 'en' ? `${amt} was cut from your payout` : lang === 'hi' ? `${amt} आपके पेमेंट से कटे` : `${amt} aapke payout se kate`) : bd.intro
    rest = parts.filter((_, k) => k !== j && !(j > 0 && k === 0))
    if (bd.tail) rest = [bd.tail, ...rest]
    break
  }
  // Keep only what the merchant must act on (a question or a next step); drop extra information.
  const detail = (usedBreakdown ? rest.filter((x) => needsYou.test(x)) : rest).slice(0, 2).join(' ').slice(0, 190)
  return { kind, chip, headline, context, factsTitle, detail, facts }
}
