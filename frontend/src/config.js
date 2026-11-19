export const SARVAM_URL = import.meta.env.VITE_SARVAM_URL || 'http://localhost:8001'
export const PAYTM_URL = import.meta.env.VITE_PAYTM_URL || 'http://localhost:8002'
export const MERCHANT_URL = import.meta.env.VITE_MERCHANT_URL || 'http://localhost:8003'
export const MID = import.meta.env.VITE_MID || 'PAYTM_MERCH_8821'

// Sarvam Voice Agent (Samvaad) for the Sales discovery call. The three ids are not secret; the API key is NEVER in the browser:
// requests go to SARVAM_PROXY, which adds the key server-side (vite dev proxy locally, proxy/sarvam-proxy.mjs when deployed).
export const SALES_AGENT = {
  org: import.meta.env.VITE_SARVAM_ORG_ID || '',
  workspace: import.meta.env.VITE_SARVAM_WORKSPACE_ID || '',
  app: import.meta.env.VITE_SARVAM_APP_ID || '',
  proxy: import.meta.env.VITE_SARVAM_PROXY || '/api/sarvam/',
}
export const SALES_READY = !!(SALES_AGENT.org && SALES_AGENT.workspace && SALES_AGENT.app)
