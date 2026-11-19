import { PAYTM_URL, MERCHANT_URL, MID } from './config.js'

async function req(url, opts = {}, timeout = 15000) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeout)
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal })
    if (!r.ok) {
      const err = new Error(`HTTP ${r.status}`)
      err.status = r.status
      err.body = await r.json().catch(() => null)
      throw err
    }
    return await r.json()
  } finally {
    clearTimeout(t)
  }
}
const post = (url, body, timeout) => req(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }, timeout)

// Which backends are reachable (8003 is required for live mode; 8002 is optional, 8003 falls back to mock Paytm).
// sarvam: 'live' | 'mock' | 'down' | null (from 8003's /health). 'mock' means no SARVAM_API_KEY: voice is off.
export async function checkServices() {
  const ok = (u) => req(u, {}, 2500).then(() => true).catch(() => false)
  const [health, paytm] = await Promise.all([req(`${MERCHANT_URL}/health`, {}, 3500).catch(() => null), ok(`${PAYTM_URL}/ledger/${MID}`)])
  return { merchant: !!health, paytm, sarvam: health?.sarvam_mode || null }
}

export const getLedger = (mid = MID) => req(`${PAYTM_URL}/ledger/${mid}`, {}, 3000).catch(() => null)
export const getEvents = () => req(`${MERCHANT_URL}/events`, {}, 3000).catch(() => [])

// lang: the app's हि / EN tab ('hi' | 'en'). The reply text and its voice come back in that language.
export const merchantQuery = (text, mid = MID, doc_context = null, lang = 'hi') =>
  post(`${MERCHANT_URL}/merchant/query`, { text, mid, consent_granted: true, doc_context, language: lang }, 30000)

export function uploadDoc(file, doc_type, mid = MID, lang = 'hi') {
  const fd = new FormData()
  fd.append('language', lang)
  fd.append('file', file)
  fd.append('doc_type', doc_type)
  fd.append('mid', mid)
  fd.append('consent_granted', 'true')
  return req(`${MERCHANT_URL}/merchant/upload-doc`, { method: 'POST', body: fd }, 40000)
}

export const proactiveShield = (mid, scenario, lang = 'hi') => post(`${MERCHANT_URL}/merchant/proactive-shield`, { mid, scenario, consent_granted: true, language: lang }, 30000)
export const confirmDispute = (mid, packet_id, lang = 'hi') => post(`${MERCHANT_URL}/merchant/confirm-dispute`, { mid, consent_granted: true, packet_id, language: lang }, 30000)
export const confirmEdi = (mid, offer_id, pause_days = 2, lang = 'hi') => post(`${MERCHANT_URL}/merchant/confirm-edi-pause`, { mid, consent_granted: true, offer_id, pause_days, language: lang }, 30000)

// Best-effort reset of both services so a live demo starts clean.
export async function resetLive() {
  await Promise.allSettled([post(`${PAYTM_URL}/ledger/reset`, {}, 4000), post(`${MERCHANT_URL}/reset?cascade=true`, {}, 6000)])
}

export const getStrategyMemory = () => req(`${MERCHANT_URL}/merchant/strategy-memory`, {}, 3000).catch(() => null)
export const getKhataExport = () => req(`${MERCHANT_URL}/merchant/khata-export`, {}, 5000).catch(() => null)
export const khataCsvUrl = () => `${MERCHANT_URL}/merchant/khata-export?format=csv`

// Sarvam STT only (via 8003): { transcript, source, reason, message_hi }. transcript is null when nothing usable
// was heard; the caller then shows message_hi instead of answering a question nobody asked.
export function transcribe(blob, mid = MID, lang = 'hi') {
  const fd = new FormData()
  fd.append('audio', blob, 'voice.webm')
  fd.append('mid', mid)
  fd.append('consent_granted', 'true')
  fd.append('language_code', lang === 'en' ? 'en-IN' : 'hi-IN')
  return req(`${MERCHANT_URL}/merchant/transcribe`, { method: 'POST', body: fd }, 25000)
}

// Real voice path: the browser records audio and the merchant agent runs Sarvam STT + the whole pipeline.
export function queryAudio(blob, mid = MID) {
  const fd = new FormData()
  fd.append('audio', blob, 'voice.webm')
  fd.append('mid', mid)
  fd.append('consent_granted', 'true')
  return req(`${MERCHANT_URL}/merchant/query-audio`, { method: 'POST', body: fd }, 45000)
}
