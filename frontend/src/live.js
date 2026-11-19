// Live mode: calls the real services (8003 -> 8001/8002) per contract.md and turns the response
// into the same "run" shape the decision-trace UI already renders.
import { inr } from './data.js'
import { merchantQuery, uploadDoc, proactiveShield, confirmDispute, confirmEdi } from './api.js'
// Demo documents (frontend/public/demo): the real Sharma PoD sample, and a fake UPI screenshot whose UTR is not in the ledger.
const fakeUrl = '/demo/fake_upi.png'
const podUrl = '/demo/pod_9981.png'

async function demoFile(url, name) {
  const blob = await (await fetch(url)).blob()
  return new File([blob], name, { type: blob.type || 'image/png' })
}

export async function callLive(sc, m, ctx = {}) {
  if (sc.id === 'shield_cb' || sc.id === 'shield_edi') return proactiveShield(m.mid, sc.proactive)
  if (sc.id === 'confirm_cb') return confirmDispute(m.mid, ctx.packet)
  if (sc.id === 'confirm_edi') return confirmEdi(m.mid, ctx.offer_id, ctx.pause_days || 2)
  if (sc.id === 'fake') return uploadDoc(ctx.fileObj || (await demoFile(fakeUrl, 'fake_upi.png')), 'upi_screenshot', m.mid)
  if (sc.id === 'cb') return uploadDoc(ctx.fileObj || (await demoFile(podUrl, 'pod_9981.png')), 'pod', m.mid)
  return merchantQuery(ctx.utterance || sc.utterance(m), m.mid)
}

// Confirm button info for proactive responses (contract: proactive.awaiting_confirmation).
function confirmFrom(r) {
  const p = r.proactive
  if (!p) return undefined
  if (p.awaiting_confirmation === 'CONFIRM_DISPUTE' && p.dispute_packet)
    return { kind: 'dispute', packet: p.dispute_packet.packet_id, label: 'Haan, delivery proof bhej do' }
  if (p.awaiting_confirmation === 'CONFIRM_EDI_PAUSE' && p.edi_pause_offer)
    return { kind: 'edi', offer_id: p.edi_pause_offer.offer_id, pause_days: p.edi_pause_offer.pause_days || 2, saved: p.edi_pause_offer.edi_saved_inr, label: 'Haan, EDI 2 din pause karo' }
  return undefined
}

const AGENT_KEY = { IntelligenceAgent: 'intelligence', RiskPolicyAgent: 'risk', ResolutionAgent: 'resolution', LedgerOpsAgent: 'ledger' }
const pc = (v) => (typeof v === 'number' ? Math.round(v * 100) + '%' : '–')

// Real A/B/C evaluation from the merchant agent (intervention_evaluation).
function evalFrom(ie) {
  if (!ie?.options?.length) return null
  const options = ie.options.map((o) => ({
    id: o.id, label: o.label, score: Math.round((o.total ?? 0) * 100),
    why: o.blocked_by_policy ? `Blocked by policy: ${o.blocked_by_policy}` : `policy ${pc(o.scores?.policy)} · cost ${pc(o.scores?.cost)} · experience ${pc(o.scores?.ux)} · past success ${pc(o.history?.success_rate)}`,
  }))
  return { options, selected: ie.options.find((o) => o.selected)?.id || ie.selected_option_id || ie.selected }
}

export function responseToRun(sc, m, r, utterance, elapsed) {
  const pr = r.paytm_response || {}
  const pd = pr.data || {}
  const status = pr.status
  const slots = r.slots || {}
  const fraud = !!r.fraud_alert || status === 'NOT_FOUND_SUSPECTED_FAKE'
  const ticket = pr.escalation_ticket
  const pro = r.proactive
  const confirm = confirmFrom(r)
  const trace = r.paytm_agent_trace || pr.agent_trace || []
  const byAgent = Object.fromEntries(trace.map((t) => [AGENT_KEY[t.agent], t]))
  const ev = evalFrom(r.intervention_evaluation)
  const hi = r.historical_insight

  const eff = []
  if (status === 'RELEASED') eff.push({ t: 'CB_RELEASE' }, { t: 'DEFLECT' })
  if (fraud) {
    const utr = slots.utr_number || r.doc_extract?.extracted_fields?.utr_number || 'unknown'
    eff.push({ t: 'FRAUD' }, { t: 'UTR_ADD', row: { utr, amount: slots.amount || 0, app: '—', status: 'NOT_FOUND_SUSPECTED_FAKE', time: 'now', name: 'Screenshot upload' } })
  }
  if (status === 'PENDING' && slots.utr_number) eff.push({ t: 'UTR_CHECK', utr: slots.utr_number, result: 'PENDING' })
  if (r.gst_itc_logged) eff.push({ t: 'ITC', amount: r.gst_itc_logged.amount })
  if (ticket) eff.push({ t: 'TICKET', id: ticket.ticket_id || ticket.id || 'TKT-PAYTM', reason: ticket.reason || r.intent })
  if (status === 'EDI_PAUSED' || String(pd.loan_edi_status || '').startsWith('PAUSED'))
    eff.push({ t: 'LOAN', status: 'PAUSED', note: `Paused ${pd.pause_days || 2} days · saved ${inr(pd.edi_saved_inr || 0)}` })
  if (r.intent === 'MANDATE_TROUBLESHOOT' && status === 'ACTION_REQUIRED')
    eff.push({ t: 'LOAN', status: 'LINK_SENT', note: `${inr(pd.amount_inr || m.d.loan.edi)} bounced · 1-tap UPI link sent · penalty waived` })
  if (status === 'RETURN_INITIATED') eff.push({ t: 'SOUNDBOX_FIX', note: pd.pickup_ticket }, { t: 'DEFLECT' })
  if (status === 'FORECLOSURE_QUOTE_READY') eff.push({ t: 'LOAN', status: 'QUOTE', note: `Pay ${inr(pd.payable)} to close · NOC in ${pd.noc_eta_days} days` })
  if (status === 'KYC_UPDATE_LINK_SENT') eff.push({ t: 'BANK_UPDATE' })
  if (r.intent === 'DUPLICATE_RECONCILE' && pd.duplicates_found) eff.push({ t: 'REFUND_AUTO', order: '#' + pd.order_id, amount: pd.order_amount_inr }, { t: 'DEFLECT' })

  const agentStep = (key, title, fallback, extra = {}) => {
    const t = byAgent[key]
    return { key, title, say: t ? t.note : fallback, quiet: t ? t.acted === false : false, ms: t ? Math.max(1, Math.round(t.ms || 0)) : 0, ...extra }
  }
  const alert = pro?.alert?.data
  const steps = [
    { key: 'input', title: 'Input understood', say: `intent=${r.intent}`, ms: 0 },
    ...(hi ? [{ key: 'insight', title: 'What the AI knew', insight: { summary: hi.summary || hi.tip_hi, evidence: hi.evidence || [] }, ms: 0 }] : []),
    ev ? { key: 'eval', title: 'Intervention evaluation', options: ev.options, selected: ev.selected, ms: 0 }
       : { key: 'eval', title: 'Intent routing', live: true, route: { intent: r.intent, source: r.intent_source, slots, transcript: r.transcript, doc: r.doc_extract }, ms: 0 },
    { key: 'consent', title: 'DPDP consent', consent: { token: r.consent_token, purpose: String(pro?.scenario || r.intent).toLowerCase(), scope: 'a2a:dispatch', ttl_min: 15, issued: new Date().toISOString().slice(11, 19) + 'Z', mid: r.mid }, ms: 0 },
    { key: 'dispatch', title: 'A2A dispatch', request: { request_id: r.request_id, mid: r.mid, intent: r.intent, payload: slots, consent_token: r.consent_token }, response: pro ? { proactive: pro } : pr, ms: 0 },
    agentStep('intelligence', 'Intelligence', alert ? `Paytm alert: ${JSON.stringify(alert).slice(0, 110)}…` : `Paytm ledger (${r.paytm_source}) → ${status}`),
    agentStep('risk', 'Risk', fraud ? (r.fraud_alert?.message || 'UTR not found across payer apps → SUSPECTED FAKE') : 'DPDP consent token valid · no fraud flag', { tone: fraud ? 'bad' : undefined }),
    agentStep('resolution', 'Resolution', ticket ? `Escalation ticket ${ticket.ticket_id || ticket.id || ''}` : `Intent ${r.intent} handled (${status})`, { tone: ticket ? 'warn' : undefined }),
    { ...agentStep('ledger', 'Ledger Ops', r.gst_itc_logged ? `GST ITC ${inr(r.gst_itc_logged.amount)} logged to merchant sheet` : 'Paytm ledger updated'), effects: eff },
    { key: 'reply', title: 'Reply to merchant', reply: r.reply_text, tone: fraud ? 'bad' : undefined, confirm, ms: 0, effects: [] },
  ]
  return {
    sc, utterance, steps, reply: r.reply_text, live: true, elapsed,
    events: r.a2a_events || [], audio: r.audio_base64, verified: r.verified_outcome, escalated: !!ticket,
    sources: { paytm: r.paytm_source, intent: r.intent_source, reply: r.reply_source },
  }
}

// Overlay authoritative numbers from GET /ledger/{mid} (8002): counters, chargeback hold and loan status.
export function overlayLedger(L, led) {
  if (!led || typeof led !== 'object') return L
  const s = { ...L }
  const c = led.counters || {}
  if (typeof c.tickets_deflected === 'number') s.deflected = Math.max(s.deflected, c.tickets_deflected)
  if (typeof c.fraud_blocked === 'number') s.fraud = Math.max(s.fraud, c.fraud_blocked)
  const hold = led.chargeback?.hold_status
  if (hold && s.chargeback) s.chargeback = { ...s.chargeback, status: String(hold).startsWith('RELEASED') ? 'RELEASED' : 'HELD' }
  const edi = led.loan?.status || led.loan_edi_status
  if (typeof edi === 'string') {
    if (edi.startsWith('PAUSED')) s.loan = { ...s.loan, status: 'PAUSED' }
    else if (s.loan.status === 'PAUSED') s.loan = { ...s.loan, status: 'ACTIVE', note: undefined }
  }
  return s
}

// Real strategy-learning numbers from GET /merchant/strategy-memory.
export function overlayStrategy(L, sm) {
  if (!sm || typeof sm !== 'object') return L
  const s = { ...L }
  if (typeof sm.successes === 'number') s.verified = sm.successes
  if (typeof sm.verified_outcomes_learned === 'number') s.learned = sm.verified_outcomes_learned
  if (Array.isArray(sm.recent)) s.learnedLog = sm.recent.slice(0, 4).map((x) => (typeof x === 'string' ? x : x.summary || `${x.intent}: option ${x.option_id} ${x.outcome || ''}`.trim()))
  return s
}
