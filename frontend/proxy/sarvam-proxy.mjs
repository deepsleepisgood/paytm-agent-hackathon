// Tiny proxy so the browser never sees the Sarvam API key. Deploy as a Render "Web Service" (start command: node frontend/proxy/sarvam-proxy.mjs)
// and set env vars: SARVAM_API_KEY (secret) and ALLOW_ORIGIN (your frontend URL).
import http from 'node:http'
const KEY = process.env.SARVAM_API_KEY
const ORIGIN = process.env.ALLOW_ORIGIN || '*'
const UP = 'https://apps.sarvam.ai/api/app-runtime'
http.createServer(async (req, res) => {
  const cors = { 'Access-Control-Allow-Origin': ORIGIN, 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS' }
  if (req.method === 'OPTIONS') { res.writeHead(204, cors); return res.end() }
  if (!KEY) { res.writeHead(500, cors); return res.end('SARVAM_API_KEY is not set') }
  try {
    const path = req.url.replace(/^\/api\/sarvam/, '').replace(/^\//, '')
    let body
    if (!['GET', 'HEAD'].includes(req.method)) { const chunks = []; for await (const c of req) chunks.push(c); body = Buffer.concat(chunks) }
    const r = await fetch(`${UP}/${path}`, { method: req.method, headers: { 'Content-Type': req.headers['content-type'] || 'application/json', 'X-API-Key': KEY }, body })
    res.writeHead(r.status, { ...cors, 'Content-Type': r.headers.get('content-type') || 'application/json' })
    res.end(Buffer.from(await r.arrayBuffer()))
  } catch (e) { res.writeHead(502, cors); res.end(String(e)) }
}).listen(process.env.PORT || 8010)
