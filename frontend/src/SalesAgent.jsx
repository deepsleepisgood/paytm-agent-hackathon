import React, { useEffect, useRef, useState } from 'react'
import { SALES_AGENT } from './config.js'
import { AIMark } from './icons.jsx'

const READY = !!(SALES_AGENT.org && SALES_AGENT.workspace && SALES_AGENT.app)
const LBL = { IDLE: 'Ready to talk', CONNECTING: 'Connecting…', CONNECTED: 'Connected', LISTENING: 'Listening…', SPEAKING: 'Speaking…', ERROR: 'Something went wrong' }

// Live voice call with the Sarvam "Sales discovery" agent (Samvaad). Talk, see the transcript, mute or end the call.
export default function SalesAgent({ m }) {
  const [state, setState] = useState('IDLE')
  const [msgs, setMsgs] = useState([])
  const [muted, setMuted] = useState(false)
  const [err, setErr] = useState('')
  const [lvl, setLvl] = useState(0)
  const ref = useRef(null)
  const sdkRef = useRef(null)
  const logRef = useRef(null)

  useEffect(() => () => { ref.current?.stop().catch(() => {}) }, [])
  useEffect(() => { logRef.current?.scrollTo(0, 1e9) }, [msgs])

  const start = async () => {
    setErr(''); setMsgs([])
    try {
      const sdk = (sdkRef.current ||= await import('sarvam-conv-ai-sdk/browser'))
      const audioInterface = new sdk.BrowserAudioInterface(16000, { outputLevelCallback: (l) => setLvl(Math.min(1, (l.rms || 0) * 6)) })
      const agent = new sdk.ConversationAgent({
        apiKey: '', // the key is added by the proxy, never in the browser
        baseUrl: SALES_AGENT.proxy,
        config: {
          org_id: SALES_AGENT.org, workspace_id: SALES_AGENT.workspace, app_id: SALES_AGENT.app,
          user_identifier: m.mid, user_identifier_type: 'custom',
          interaction_type: sdk.InteractionType.CALL, input_sample_rate: 16000, output_sample_rate: 16000,
          agent_variables: { merchant_name: m.profile.name, merchant_id: m.mid },
        },
        audioInterface,
        stateCallback: (s) => setState(String(s).toUpperCase()),
        transcriptCallback: async (x) => setMsgs((p) => [...p, { who: x.role === sdk.Role.USER ? 'you' : 'agent', text: x.content }]),
        endCallback: async () => { ref.current = null; setState('IDLE'); setLvl(0) },
      })
      ref.current = agent
      await agent.start()
      const ok = await agent.waitForConnect(10)
      if (!ok) throw new Error('Could not connect to the agent. Check the proxy and your ids.')
    } catch (e) {
      setErr(e?.name === 'NotAllowedError' ? 'Microphone permission is blocked. Allow it in the browser and try again.' : e?.message || 'Could not start the call.')
      setState('ERROR'); ref.current?.stop().catch(() => {}); ref.current = null
    }
  }
  const stop = async () => { try { await ref.current?.stop() } finally { ref.current = null; setState('IDLE'); setLvl(0); setMuted(false) } }
  const mute = () => { const a = ref.current; if (!a) return; if (a.isMuted()) { a.unmute(); setMuted(false) } else { a.mute(); setMuted(true) } }
  const live = ['CONNECTING', 'CONNECTED', 'LISTENING', 'SPEAKING'].includes(state)

  if (!READY) {
    return (
      <div className="sa">
        <div className="sa-card">
          <b>Connect your Sarvam sales agent</b>
          <p>Add these three ids (from the agent's “Deploy with code” page in the Sarvam dashboard) and your API key, then restart:</p>
          <pre>{'frontend/.env.local\nSARVAM_API_KEY=…            (secret, stays on the server)\nVITE_SARVAM_ORG_ID=…\nVITE_SARVAM_WORKSPACE_ID=…\nVITE_SARVAM_APP_ID=…'}</pre>
        </div>
      </div>
    )
  }
  return (
    <div className="sa">
      <div className={`sa-orb ${live ? 'on' : ''} ${state === 'SPEAKING' ? 'speak' : ''}`} style={{ '--lvl': lvl }}>
        <AIMark size={86} />
      </div>
      <div className="sa-state">{LBL[state] || state}</div>
      <p className="sa-sub">Talk to a Paytm for Business sales expert. They will ask about your shop and suggest the right products.</p>
      {err && <div className="sa-err">{err}</div>}
      <div className="sa-log" ref={logRef}>
        {msgs.map((x, i) => <div key={i} className={`sa-m ${x.who}`}><em>{x.who === 'you' ? 'You' : 'Sales expert'}</em><span>{x.text}</span></div>)}
      </div>
      <div className="sa-act">
        {!live
          ? <button className="sa-go" onClick={start}>Start voice call</button>
          : (<><button className="sa-mute" onClick={mute}>{muted ? 'Unmute' : 'Mute'}</button><button className="sa-end" onClick={stop}>End call</button></>)}
      </div>
    </div>
  )
}
