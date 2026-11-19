// Live mode: calls the real services (8003 -> 8001/8002) per contract.md and turns the response
// into the same "run" shape the decision-trace UI already renders.
import { inr } from './data.js'
import { merchantQuery, uploadDoc, proactiveShield, confirmDispute, confirmEdi } from './api.js'
import fakeUrl from '../../dataset/test_files/fake_upi.png?url'
import podUrl from '../../dataset/test_files/pod_9981.png?url'

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
    return { kind: 'dispute', packet: p.dispute_packet.packet_id, label: '✅ Haan, delivery proof bhej do' }
  if (p.awaiting_confirmation === 'CONFIRM_EDI_PAUSE' && p.edi_pause_offer)
    return { kind: 'edi', offer_id: p.edi_pause_offer.offer_id, pause_days: p.edi_pause_offer.pause_days || 2, saved: p.edi_pause_offer.edi_saved_inr, label: '✅ Haan, EDI 2 din pause karo' }
  return undefined
}

export function responseToRun(sc, m, r, utterance, elapsed) {
  const pr = r.paytm_response || {}
  const pd = pr.data || {}
  const status = pr.status
  const slots = r.slots || {}
  const fraud = !!r.fraud_alert || status === 'NOT_FOUND_SUSPECTED_FAKE'
  const ticket = pr.escalation_ticket
  const action = pr.action_required
  const pro = r.proactive
  const confirm = confirmFrom(r)

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
  const win = !ticket && !confirm
  const alert = pro?.alert?.data

  const steps = [
    { key: 'input', title: 'Input understood', say: `intent=${r.intent}`, ms: 0 },
    { key: 'consent', title: 'DPDP consent', consent: { token: r.consent_token, purpose: String(pro?.scenario || r.intent).toLowerCase(), scope: 'a2a:dispatch', ttl_min: 15, issued: new Date().toISOString().slice(11, 19) + 'Z', mid: r.mid }, ms: 0 },
    { key: 'eval', title: 'Intent routing', live: true, route: { intent: r.intent, source: r.intent_source, slots, transcript: r.transcript, doc: r.doc_extract }, ms: 0 },
    { key: 'dispatch', title: 'A2A dispatch', request: { request_id: r.request_id, mid: r.mid, intent: r.intent, payload: slots, consent_token: r.consent_token }, response: pro ? { proactive: pro } : pr, ms: 0 },
    { key: 'intelligence', title: 'Intelligence', say: alert ? `Paytm alert: ${JSON.stringify(alert).slice(0, 110)}…` : `Paytm ledger (${r.paytm_source}) → ${status}${pd.variance ? ` · variance ${inr(pd.variance)}` : ''}`, ms: 0 },
    { key: 'risk', title: 'Risk', say: fraud ? (r.fraud_alert?.message || r.fraud_alert?.reason || 'UTR not found across payer apps → SUSPECTED FAKE') : 'DPDP consent token valid · no fraud flag', tone: fraud ? 'bad' : undefined, ms: 0 },
    { key: 'resolution', title: 'Resolution', say: ticket ? `Escalation ticket ${ticket.ticket_id || ticket.id || ''}` : action ? action.message || action.type : `Intent ${r.intent} handled (${status})`, tone: ticket ? 'warn' : undefined, ms: 0 },
    { key: 'ledger', title: 'Ledger Ops', say: r.gst_itc_logged ? `GST ITC ${inr(r.gst_itc_logged.amount)} logged to merchant sheet` : 'Paytm ledger updated', effects: eff, ms: 0 },
    { key: 'reply', title: 'Reply to merchant', reply: r.reply_text, tone: fraud ? 'bad' : undefined, confirm, ms: 0, effects: win ? [{ t: 'OUTCOME' }, { t: 'LEARN', text: `${r.intent}: resolved via live agents` }] : [] },
  ]
  return {
    sc, utterance, steps, reply: r.reply_text, live: true, elapsed,
    events: r.a2a_events || [], audio: r.audio_base64,
    sources: { paytm: r.paytm_source, intent: r.intent_source, reply: r.reply_source },
  }
}

// Overlay authoritative numbers from GET /ledger/{mid} (8002) when those keys exist. Shape is read defensively.
export function overlayLedger(L, led) {
  if (!led || typeof led !== 'object') return L
  const s = { ...L }
  const pick = (...ks) => ks.map((k) => led[k]).find((v) => v !== undefined && v !== null)
  const defl = pick('tickets_deflected', 'deflected')
  const fr = pick('frauds_blocked_count', 'fraud_blocked', 'frauds_blocked')
  if (typeof defl === 'number') s.deflected = defl
  if (typeof fr === 'number') s.fraud = fr
  const cb = pick('chargeback_status') || led.chargeback?.status
  if (cb && s.chargeback) s.chargeback = { ...s.chargeback, status: String(cb).startsWith('RELEASED') ? 'RELEASED' : 'HELD' }
  const edi = pick('loan_edi_status')
  if (typeof edi === 'string') s.loan = { ...s.loan, status: edi.startsWith('PAUSED') ? 'PAUSED' : s.loan.status === 'PAUSED' ? 'ACTIVE' : s.loan.status }
  return s
}
