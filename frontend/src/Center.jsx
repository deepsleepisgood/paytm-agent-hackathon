import React, { useState } from 'react'
import { I, AIMark } from './icons.jsx'

const AGENTS = [
  { key: 'intelligence', name: 'Intelligence', ic: '1', does: 'Reads the data' },
  { key: 'risk', name: 'Risk', ic: '2', does: 'Checks safety & policy' },
  { key: 'resolution', name: 'Resolution', ic: '3', does: 'Decides the fix' },
  { key: 'ledger', name: 'Ledger Ops', ic: '4', does: 'Updates the books' },
]
const STAGES = [
  { label: 'Understand', keys: ['input'] },
  { label: 'Decide', keys: ['insight', 'eval'] },
  { label: 'Permission', keys: ['consent'] },
  { label: 'Paytm agents', keys: ['dispatch', 'intelligence', 'risk', 'resolution', 'ledger'] },
  { label: 'Reply', keys: ['reply'] },
]
const CAPTION = {
  input: 'Buddy understood the request',
  consent: 'Checking the merchant’s permission (DPDP)',
  insight: 'Buddy is recalling this merchant’s history',
  eval: 'Buddy is comparing 3 ways to help',
  dispatch: 'Sending a secure request to Paytm',
  intelligence: 'Paytm is reading the data',
  risk: 'Paytm is checking safety and policy',
  resolution: 'Paytm is deciding the fix',
  ledger: 'Paytm is updating the books',
  reply: 'Answer sent to the merchant',
}


/* ---------- Autonomous agent team: animated, step by step ---------- */
const ico = (children) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
const FLOW = [
  { id: 'buddy', key: 'eval', from: 0, name: 'Merchant Buddy', side: 'Merchant side', role: 'Understands, recalls and decides', tone: 'blue', think: 'Comparing three ways to help…', link: 'Decision', brand: true },
  { id: 'consent', key: 'consent', name: 'DPDP Consent Gate', side: 'Compliance', role: 'Nothing is shared without permission', tone: 'teal', think: 'Verifying the merchant’s consent…', link: 'Signed request', icon: ico(<><rect x="5" y="10.5" width="14" height="9.5" rx="2.4" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /><path d="M9.6 15.2l1.7 1.7 3.2-3.4" /></>) },
  { id: 'intelligence', key: 'intelligence', name: 'Intelligence Agent', side: 'Paytm side', role: 'Reads the ledger and history', tone: 'indigo', think: 'Reading the ledger and merchant history…', link: 'Insights', icon: ico(<><circle cx="6" cy="7" r="2.1" /><circle cx="18" cy="7" r="2.1" /><circle cx="12" cy="17.5" r="2.1" /><path d="M7.7 8.4l3 7.4M16.3 8.4l-3 7.4M8.2 7h7.6" /></>) },
  { id: 'risk', key: 'risk', name: 'Risk & Policy Agent', side: 'Paytm side', role: 'Fraud, limits and policy', tone: 'amber', think: 'Checking policy, limits and fraud signals…', link: 'Cleared', icon: ico(<><path d="M12 3.2l7 2.8v5.4c0 4.4-2.9 7.6-7 9.4-4.1-1.8-7-5-7-9.4V6z" /><path d="M9.2 12l2.1 2.1 3.6-3.8" /></>) },
  { id: 'resolution', key: 'resolution', name: 'Resolution Agent', side: 'Paytm side', role: 'Chooses and applies the fix', tone: 'sky', think: 'Choosing and applying the best fix…', link: 'Decision', icon: ico(<><circle cx="6" cy="6" r="2.1" /><circle cx="6" cy="18" r="2.1" /><circle cx="18" cy="12" r="2.1" /><path d="M8 6h3a3 3 0 0 1 3 3v0M8 18h3a3 3 0 0 0 3-3v0M14 12h2" /></>) },
  { id: 'ledger', key: 'ledger', name: 'Ledger Ops Agent', side: 'Paytm side', role: 'Updates the books', tone: 'green', think: 'Writing the result to the ledger…', link: '', icon: ico(<><path d="M6 4.5h10.5A1.5 1.5 0 0 1 18 6v13.5H7.5A1.5 1.5 0 0 1 6 18z" /><path d="M9.5 9h5M9.5 12.5h5M9.5 16h3" /></>) },
]

function AgentFlow({ run, reveal, done, escalated, totalMs }) {
  const steps = run.steps
  const at = (key) => steps.findIndex((s) => s.key === key)
  const get = (key) => steps.find((s) => s.key === key)
  const stateOf = (n) => {
    const i = at(n.key)
    if (i < 0) return 'idle'
    if (reveal > i) return 'done'
    if (reveal >= (n.from ?? i)) return 'work'
    return 'idle'
  }
  const states = FLOW.map(stateOf)
  const doneN = states.filter((s) => s === 'done').length
  const resultOf = (n) => {
    const s = get(n.key)
    if (!s) return ''
    if (n.id === 'buddy') {
      if (s.options) { const o = s.options.find((x) => x.id === s.selected); return `Chose option ${s.selected}: ${o ? o.label : ''}` }
      return `Understood: ${s.route?.intent || 'request'}`
    }
    if (n.id === 'consent') return `Token ${s.consent.token.slice(0, 18)}… · ${s.consent.purpose.replace(/_/g, ' ')}`
    return s.say
  }
  return (
    <div className="af">
      <div className="af-h">
        <div><b>Autonomous agent team</b><span>Each agent works on its own and hands over to the next</span></div>
        <div className="af-chips">
          <i>{doneN}/{FLOW.length} done</i>
          <i className={escalated ? 'esc' : 'auto'}>{escalated ? '1 human handoff' : '0 humans in the loop'}</i>
          {done && <i>{(totalMs / 1000).toFixed(1)}s</i>}
        </div>
      </div>
      <div className="af-list">
        {FLOW.map((n, k) => {
          const st = states[k]
          const s = get(n.key)
          const tone = st === 'done' && s?.tone ? s.tone : ''
          const linkActive = k > 0 && states[k - 1] === 'done' && st === 'work'
          return (
            <div key={n.id} className={`af-node ${st} t-${n.tone} ${tone}`}>
              <div className="af-rail">
                <div className="af-av">
                  {n.brand ? <AIMark size={30} /> : n.icon}
                  <span className="af-tick"><I.Check size={11} /></span>
                </div>
                {k < FLOW.length - 1 && (
                  <div className={`af-link ${states[k] === 'done' ? 'on' : ''} ${states[k] === 'done' && states[k + 1] === 'work' ? 'go' : ''}`}>
                    <span className="af-pkt" />
                  </div>
                )}
              </div>
              <div className="af-card">
                <div className="af-top">
                  <b>{n.name}</b>
                  <span className="af-st">{st === 'done' ? 'Done' : st === 'work' ? <>Working<span className="af-dots"><i /><i /><i /></span></> : 'Waiting'}</span>
                </div>
                <div className="af-role">{n.side} · {n.role}</div>
                {st === 'work' && <div className="af-think">{k > 0 && FLOW[k - 1].link && <span className="af-recv">Received · {FLOW[k - 1].link}</span>}<span>{n.think}</span><div className="af-shim" /></div>}
                {st === 'done' && <div className="af-out">{resultOf(n)}</div>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function Center({ run, reveal, busy, onTry, demoActive }) {
  const [tech, setTech] = useState(false)
  const steps = run?.steps || []
  const idx = (key) => steps.findIndex((s) => s.key === key)
  const shown = (key) => idx(key) >= 0 && idx(key) < reveal
  const get = (key) => steps.find((s) => s.key === key)
  const done = run && reveal >= steps.length
  const cur = run && reveal > 0 ? steps[Math.min(reveal, steps.length) - 1] : null
  const stageNow = run ? STAGES.findIndex((st) => st.keys.includes(cur?.key)) : -1
  const consent = get('consent'), ev = get('eval'), disp = get('dispatch'), ins = get('insight')
  const escalated = run?.live ? !!run.escalated : ev && ev.selected === 'C' && shown('eval')
  const awaiting = shown('reply') && !!get('reply')?.confirm
  const totalMs = run?.live ? run.elapsed || 0 : steps.reduce((a, s) => a + (s.ms || 0), 0)

  return (
    <div className="col center">
      <div className="col-h">
        <div><b>How the AI is solving it</b><div className="muted xs">Merchant AI Buddy ⇄ Paytm AI agents · live decision trace</div></div>
        <span className={`state ${run ? (done ? 'done' : 'run') : ''}`}>{run ? (done ? 'Resolved' : 'Working…') : 'Ready'}</span>
      </div>

      {run && (
        <>
          <div className="utter"><span className="muted xs">Merchant asked</span><div>“{run.utterance}”</div><span className="chip-i">{run.sc.intent}</span></div>
          <div className="stepper">
            {STAGES.map((st, k) => (
              <div key={st.label} className={`stp ${k < stageNow || (done && true) ? 'done' : ''} ${k === stageNow && !done ? 'now' : ''}`}>
                <span className="dot">{k < stageNow || done ? '✓' : k + 1}</span><em>{st.label}</em>
              </div>
            ))}
          </div>
          <div className={`caption ${done ? 'ok' : ''}`}>{done ? 'Done — see the result below' : `${CAPTION[cur?.key] || 'Starting…'}…`}</div>
        </>
      )}

      {run && <AgentFlow run={run} reveal={reveal} done={done} escalated={escalated} totalMs={totalMs} />}

      {!run && (
        <div className="empty">
          <div className="e-ic"><AIMark size={64} /></div>
          <b>Pick a problem on the phone to start</b>
          <span className="muted sm">Watch the Merchant Buddy ask for permission, weigh options, and hand work to four Paytm AI agents — all in seconds.</span>
          <div className="how">
            <span><i>1</i>Merchant asks</span><span><i>2</i>Buddy decides</span><span><i>3</i>Paytm agents act</span><span><i>4</i>Books update</span>
          </div>
          <div className="try">
            <button className="cta" disabled={busy} onClick={() => onTry('settle')}>Try: “Why was money deducted?”</button>
            <button className="ghost" disabled={busy} onClick={() => onTry('fake')}>Try: fake screenshot</button>
          </div>
        </div>
      )}

      {shown('insight') && ins && (
        <div className="tcard in">
          <div className="t-h"><span className="n">0</span><b>What the AI remembered about this merchant</b></div>
          <div className="plain">{ins.insight.summary}</div>
          {ins.insight.evidence?.length > 0 && <ul className="ev">{ins.insight.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>}
        </div>
      )}

      {shown('eval') && ev && ev.live && (
        <div className="tcard in">
          <div className="t-h"><span className="n">1</span><b>Merchant Buddy understood the request</b><span className="chip-i sel">{ev.route.source === 'llm' ? 'Sarvam LLM' : ev.route.source === 'document' ? 'Document' : 'Keyword fallback'}</span></div>
          <div className="kv">
            <span>Intent</span><code>{ev.route.intent}</code>
            {Object.entries(ev.route.slots || {}).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => (<React.Fragment key={k}><span>{k}</span><code>{String(v)}</code></React.Fragment>))}
            {ev.route.transcript && (<><span>Heard</span><code>{ev.route.transcript}</code></>)}
          </div>
        </div>
      )}

      {shown('eval') && ev && !ev.live && (
        <div className="tcard in">
          <div className="t-h"><span className="n">1</span><b>Merchant Buddy compares 3 options</b><span className="chip-i sel">Chose {ev.selected}</span></div>
          {ev.options.map((o) => (
            <div key={o.id} className={`opt ${o.id === ev.selected ? 'sel' : ''}`}>
              <span className="o-id">{o.id}</span>
              <div className="o-mid"><div className="o-l">{o.label}</div><div className="muted xs">{o.why}</div><div className="o-bar"><i style={{ width: o.score + '%' }} /></div></div>
              <span className="o-sc" title="Fit score out of 100">{o.score}</span>
            </div>
          ))}
        </div>
      )}

      {shown('reply') && (
        <div className={`tcard in result ${get('reply').tone === 'bad' ? 'bad' : awaiting || escalated ? 'esc' : 'good'}`}>
          <div className="res-h">
            <span className="res-b">{get('reply').tone === 'bad' ? 'Fraud blocked' : awaiting ? 'Waiting for your sign-off' : escalated ? 'Handed to a human' : 'Resolved by AI'}</span>
            <span className="muted xs">{run.live ? `${(totalMs / 1000).toFixed(1)}s live round trip` : `${(totalMs / 1000).toFixed(1)}s of agent time`}</span>
          </div>
          <div className="sm">“{get('reply').reply}”</div>
          {run.live && run.sources && (
            <div className="srcs">
              <span className="chip-i">Paytm: {run.sources.paytm}</span><span className="chip-i">Intent: {run.sources.intent}</span><span className="chip-i">Reply: {run.sources.reply}</span>
            </div>
          )}
          <div className="muted xs">Check the right column — the ledger already changed.</div>
        </div>
      )}

      {done && run.live && run.events.length > 0 && (
        <div className="tcard in">
          <div className="t-h"><b>A2A & DPDP compliance log</b><span className="muted xs">real events from :8003</span></div>
          {run.events.map((e) => (
            <div key={e.seq} className="evt"><code>{e.type}</code><span className="muted xs">{e.actor}</span><div className="sm">{e.summary}</div></div>
          ))}
        </div>
      )}

      {run && shown('dispatch') && disp && (
        <div className="tech">
          <button onClick={() => setTech(!tech)}>{tech ? '▾' : '▸'} Technical details (A2A request / response)</button>
          {tech && (
            <div className="json">
              <div><span className="muted xs">REQUEST · :8003 → :8002 /a2a/dispatch</span><pre>{JSON.stringify(disp.request, null, 1)}</pre></div>
              <div><span className="muted xs">RESPONSE</span><pre>{JSON.stringify(disp.response, null, 1)}</pre></div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
