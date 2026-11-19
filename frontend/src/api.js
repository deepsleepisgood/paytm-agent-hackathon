import { PAYTM_URL, MERCHANT_URL, MID } from './config.js'

async function req(url, opts = {}, timeout = 4000) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeout)
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal })
    if (!r.ok) throw new Error(`${r.status}`)
    return await r.json()
  } finally {
    clearTimeout(t)
  }
}

// Returns null when the backend is offline so the UI can fall back to seed data.
export const getLedger = (mid = MID) => req(`${PAYTM_URL}/ledger/${mid}`).catch(() => null)

export const merchantQuery = (text, doc_context = null) =>
  req(
    `${MERCHANT_URL}/merchant/query`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, mid: MID, consent_granted: true, doc_context }),
    },
    30000,
  )

export const getEvents = () => req(`${MERCHANT_URL}/events`).catch(() => [])
