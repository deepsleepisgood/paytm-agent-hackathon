import React, { useState } from 'react'
import { I } from './icons.jsx'

const AGENTS = [
  { key: 'intelligence', name: 'Intelligence', ic: '1', does: 'Reads the data' },
  { key: 'risk', name: 'Risk', ic: '2', does: 'Checks safety & policy' },
  { key: 'resolution', name: 'Resolution', ic: '3', does: 'Decides the fix' },
  { key: 'ledger', name: 'Ledger Ops', ic: '4', does: 'Updates the books' },
]
const STAGES = [
  { label: 'Understand', keys: ['input'] },
  { label: 'Permission', keys: ['consent'] },
  { label: 'Decide', keys: ['eval'] },
  { label: 'Paytm agents', keys: ['dispatch', 'intelligence', 'risk', 'resolution', 'ledger'] },
  { label: 'Reply', keys: ['reply'] },
]
const CAPTION = {
  input: 'Buddy understood the request',
  consent: 'Checking the merchant’s permission (DPDP)',
  eval: 'Buddy is comparing 3 ways to help',
  dispatch: 'Sending a secure request to Paytm',
  intelligence: 'Paytm is reading the data',
  risk: 'Paytm is checking safety and policy',
  resolution: 'Paytm is deciding the fix',
  ledger: 'Paytm is updating the books',
  reply: 'Answer sent to the merchant',
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
  const consent = get('consent'), ev = get('eval'), disp = get('dispatch')
  const escalated = ev && ev.selected === 'C' && shown('eval')
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

      {!run && (
        <div className="empty">
          <div className="e-ic"><I.Spark size={26} /></div>
          <b>Pick a problem on the phone to start</b>
          <span className="muted sm">Watch the Merchant Buddy ask for permission, weigh options, and hand work to four Paytm AI agents — all in seconds.</span>
          <div className="how">
            <span><i>1</i>Merchant asks</span><span><i>2</i>Buddy decides</span><span><i>3</i>Paytm agents act</span><span><i>4</i>Books update</span>
          </div>
          <div className="try">
            <button className="cta" disabled={busy} onClick={() => onTry('settle')}>Try: “Paisa kahan kata?”</button>
            <button className="ghost" disabled={busy} onClick={() => onTry('fake')}>Try: fake screenshot</button>
          </div>
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

      {shown('consent') && consent && (
        <div className="tcard in">
          <div className="t-h"><span className="ok-dot"><I.Check size={12} /></span><b>Merchant’s permission verified</b><span className="muted xs">DPDP · by Paytm Risk Agent</span></div>
          <div className="plain">Allowed purpose: <b>{consent.consent.purpose.replace(/_/g, ' ')}</b> · valid {consent.consent.ttl_min} min</div>
          <div className="kv">
            <span>Token</span><code>{consent.consent.token}</code>
            <span>Scope</span><code>{consent.consent.scope}</code>
            <span>Issued</span><code>{consent.consent.issued}</code>
          </div>
        </div>
      )}

      {AGENTS.some((a) => shown(a.key)) && (
        <div className="tcard in">
          <div className="t-h"><span className="n">2</span><b>Four Paytm AI agents work in order</b></div>
          <div className="mesh">
            {AGENTS.map((a, k) => {
              const on = shown(a.key), s = get(a.key)
              return (
                <React.Fragment key={a.key}>
                  <div className={`node ${on ? 'on' : ''} ${on && s.tone === 'bad' ? 'bad' : ''} ${on && s.tone === 'warn' ? 'warn' : ''}`}>
                    <span className="n-ic">{a.ic}</span><b>{a.name}</b><span className="n-s">{a.does}</span>
                  </div>
                  {k < 3 && <span className={`arrow ${on ? 'on' : ''}`}>→</span>}
                </React.Fragment>
              )
            })}
          </div>
          {AGENTS.filter((a) => shown(a.key)).map((a) => {
            const s = get(a.key)
            return (
              <div key={a.key} className={`ag ${s.tone || ''}`}>
                <span className="ag-ic">{a.ic}</span>
                <div><b>{a.name}</b><div className="sm">{s.say}</div></div>
              </div>
            )
          })}
        </div>
      )}

      {shown('reply') && (
        <div className={`tcard in result ${get('reply').tone === 'bad' ? 'bad' : escalated ? 'esc' : 'good'}`}>
          <div className="res-h">
            <span className="res-b">{get('reply').tone === 'bad' ? 'Fraud blocked' : escalated ? 'Handed to a human' : 'Resolved by AI'}</span>
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
