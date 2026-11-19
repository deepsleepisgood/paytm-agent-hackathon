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


/* ---------- Autonomous agent team: a relay, one agent in the spotlight at a time ---------- */
const ico = (children, s = 22) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
const ICONS = {
  consent: <><rect x="5" y="10.5" width="14" height="9.5" rx="2.4" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /><path d="M9.6 15.2l1.7 1.7 3.2-3.4" /></>,
  intelligence: <><circle cx="6" cy="7" r="2.1" /><circle cx="18" cy="7" r="2.1" /><circle cx="12" cy="17.5" r="2.1" /><path d="M7.7 8.4l3 7.4M16.3 8.4l-3 7.4M8.2 7h7.6" /></>,
  risk: <><path d="M12 3.2l7 2.8v5.4c0 4.4-2.9 7.6-7 9.4-4.1-1.8-7-5-7-9.4V6z" /><path d="M9.2 12l2.1 2.1 3.6-3.8" /></>,
  resolution: <><circle cx="6" cy="6" r="2.1" /><circle cx="6" cy="18" r="2.1" /><circle cx="18" cy="12" r="2.1" /><path d="M8 6h3a3 3 0 0 1 3 3v0M8 18h3a3 3 0 0 0 3-3v0M14 12h2" /></>,
  ledger: <><path d="M6 4.5h10.5A1.5 1.5 0 0 1 18 6v13.5H7.5A1.5 1.5 0 0 1 6 18z" /><path d="M9.5 9h5M9.5 12.5h5M9.5 16h3" /></>,
}
const FLOW = [
  { id: 'buddy', key: 'eval', from: 0, name: 'Merchant Buddy', short: 'Buddy', side: 'Merchant side', role: 'Understands, recalls and decides', tone: 'blue', link: 'Decision', brand: true,
    now: 'Working out the best way to help', tasks: ['Understanding what the merchant said', 'Recalling this merchant’s history', 'Scoring options A, B and C', 'Picking the best action'], tools: ['Memory', 'Intent router', 'Option scorer'] },
  { id: 'consent', key: 'consent', name: 'DPDP Consent Gate', short: 'Consent', side: 'Compliance', role: 'Nothing is shared without permission', tone: 'teal', link: 'Signed request',
    now: 'Making sure the merchant allowed this', tasks: ['Minting a consent token', 'Checking purpose and scope', 'Signing the agent-to-agent request'], tools: ['DPDP ledger', 'Token service'] },
  { id: 'intelligence', key: 'intelligence', name: 'Intelligence Agent', short: 'Intel', side: 'Paytm side', role: 'Reads the ledger and history', tone: 'indigo', link: 'Insights',
    now: 'Reading the data behind this request', tasks: ['Opening the merchant ledger', 'Reading transactions and history', 'Matching the facts to the request'], tools: ['Ledger', 'Merchant history', 'Connectors'] },
  { id: 'risk', key: 'risk', name: 'Risk & Policy Agent', short: 'Risk', side: 'Paytm side', role: 'Fraud, limits and policy', tone: 'amber', link: 'Cleared',
    now: 'Checking that this is safe and allowed', tasks: ['Verifying the consent token', 'Running fraud and policy checks', 'Checking limits (₹5,000 auto-limit)'], tools: ['Policy engine', 'NPCI log', 'Fraud signals'] },
  { id: 'resolution', key: 'resolution', name: 'Resolution Agent', short: 'Fix', side: 'Paytm side', role: 'Chooses and applies the fix', tone: 'sky', link: 'Decision',
    now: 'Deciding and applying the fix', tasks: ['Choosing the right remedy', 'Applying the decision', 'Preparing the merchant’s reply'], tools: ['Decision rules', 'Reply builder'] },
  { id: 'ledger', key: 'ledger', name: 'Ledger Ops Agent', short: 'Ledger', side: 'Paytm side', role: 'Updates the books', tone: 'green', link: '',
    now: 'Recording what happened', tasks: ['Writing entries to the ledger', 'Updating counters and status', 'Logging for audit (DPDP)'], tools: ['Ledger DB', 'Audit log', 'Counters'] },
]

// Little AI robots, one personality each (same head, different eyes / mouth / gear).
function Robot({ id, size }) {
  const eyes = {
    buddy: <><circle className="rb-eye" cx="15.6" cy="19.2" r="2.2" /><circle className="rb-eye" cx="24.4" cy="19.2" r="2.2" /></>,
    consent: <><circle className="rb-eye" cx="15.6" cy="19.2" r="2.2" /><circle className="rb-eye" cx="24.4" cy="19.2" r="2.2" /></>,
    intelligence: <><circle className="rb-eye" cx="15.6" cy="19.2" r="2.4" /><circle className="rb-eye" cx="24.4" cy="19.2" r="2.4" /><circle cx="15.6" cy="19.2" r="4.6" fill="none" className="rb-neon" strokeWidth="1" opacity=".8" /><circle cx="24.4" cy="19.2" r="4.6" fill="none" className="rb-neon" strokeWidth="1" opacity=".8" /><path d="M20 19.2h0" className="rb-neon" /></>,
    risk: <rect className="rb-eye rb-bar" x="13" y="17.6" width="14" height="3.4" rx="1.7" />,
    resolution: <><path className="rb-eye" d="M13.2 20.4a2.4 2.4 0 0 1 4.8 0" fill="none" className="rb-neon" strokeWidth="1.9" strokeLinecap="round" /><path className="rb-eye" d="M22 20.4a2.4 2.4 0 0 1 4.8 0" fill="none" className="rb-neon" strokeWidth="1.9" strokeLinecap="round" /></>,
    ledger: <><rect className="rb-eye" x="13.2" y="17.2" width="4.6" height="4.2" rx="1.2" /><rect className="rb-eye" x="22.2" y="17.2" width="4.6" height="4.2" rx="1.2" /></>,
  }[id]
  const mouth = id === 'buddy'
    ? <g className="rb-mouth">{[0, 1, 2, 3, 4].map((k) => <rect key={k} x={15.6 + k * 2.2} y="23" width="1.3" height="2.2" rx=".65" className="rb-fill" style={{ '--k': k }} />)}</g>
    : id === 'ledger'
      ? <path d="M16 24.1h8" className="rb-neon" strokeWidth="1.3" strokeLinecap="round" strokeDasharray="1.6 1.6" />
      : <path d="M17 24.1c1.8 1.2 4.2 1.2 6 0" fill="none" className="rb-neon" strokeWidth="1.3" strokeLinecap="round" />
  const gear = {
    buddy: <path d="M8 18a12 12 0 0 1 24 0" fill="none" className="rb-neon" strokeWidth="1.7" strokeLinecap="round" />,
    consent: <path d="M9 11.5h22" className="rb-neon" strokeWidth="2.4" strokeLinecap="round" opacity=".9" />,
    intelligence: <g className="rb-fill"><circle cx="13" cy="5" r="1.3" /><circle cx="27" cy="5" r="1.3" /><path d="M13 6l7 3.5M27 6l-7 3.5" className="rb-neon" strokeWidth=".9" /></g>,
    risk: <path d="M12 11.5l8-3.2 8 3.2" fill="none" className="rb-neon" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />,
    resolution: <path d="M10 10.5a10 4.2 0 0 1 20 0z" className="rb-fill" opacity=".92" />,
    ledger: <rect x="12.5" y="6.6" width="15" height="2.4" rx="1.2" className="rb-fill" opacity=".9" />,
  }[id]
  return (
    <svg className={`rb rb-${id}`} viewBox="0 0 40 40" width={size} height={size} aria-hidden="true">
      {/* neon antenna */}
      <line className="rb-neon" x1="20" y1="5.4" x2="20" y2="9.4" strokeWidth="1.6" strokeLinecap="round" />
      <circle className="rb-ant rb-fill" cx="20" cy="3.8" r="2.3" />
      {gear}
      {/* ear lights */}
      <rect className="rb-fill rb-ear" x="3.4" y="17" width="3.4" height="7.8" rx="1.7" />
      <rect className="rb-fill rb-ear" x="33.2" y="17" width="3.4" height="7.8" rx="1.7" />
      {/* cartoon metal head with neon rim */}
      <rect className="rb-head" x="7" y="9.4" width="26" height="22.4" rx="7.5" />
      <path className="rb-shine" d="M10.5 12.6h10" strokeWidth="1.2" strokeLinecap="round" />
      {/* circuit cheeks */}
      <path className="rb-neon rb-circ" d="M9.4 27.6h3.6v2.2h2.8M30.6 27.6H27v2.2h-2.8" fill="none" strokeWidth=".9" strokeLinecap="round" strokeLinejoin="round" />
      {/* glowing visor */}
      <rect className="rb-visor" x="10.2" y="13.6" width="19.6" height="12.6" rx="5.2" />
      {eyes}{mouth}
      {/* shoulders + badge */}
      <path className="rb-body" d="M12.5 38.8v-2.6a3.8 3.8 0 0 1 3.8-3.8h7.4a3.8 3.8 0 0 1 3.8 3.8v2.6z" />
      <path className="rb-neon" d="M16 35.2h8" strokeWidth="1" strokeLinecap="round" opacity=".8" />
      <circle className="rb-badge" cx="31" cy="33.2" r="5.6" />
      <g transform="translate(26.4 28.6) scale(.385)" fill="none" className="rb-neon" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">{id === 'buddy' ? <path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" /> : ICONS[id]}</g>
    </svg>
  )
}

function Avatar({ n, size = 44 }) {
  return (
    <div className="ag-av" style={{ '--s': size + 'px' }}>
      <Robot id={n.id} size={Math.round(size * 0.86)} />
    </div>
  )
}

function AgentFlow({ run, reveal, done, escalated, totalMs }) {
  const steps = run.steps
  const durs = run.durs || []
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
  const cur = states.findIndex((s) => s === 'work')
  const lastDone = states.lastIndexOf('done')
  const spot = cur >= 0 ? cur : -1
  const resultOf = (n) => {
    const s = get(n.key)
    if (!s) return ''
    if (n.id === 'buddy') {
      if (s.options) { const o = s.options.find((x) => x.id === s.selected); return `Chose option ${s.selected}: ${o ? o.label : ''}` }
      return `Understood: ${s.route?.intent || 'the request'}`
    }
    if (n.id === 'consent') return `Token ${s.consent.token.slice(0, 18)}… · ${s.consent.purpose.replace(/_/g, ' ')}`
    return s.say
  }
  // how long the spotlighted agent has to work (ms): from when it became active to when its step is revealed
  const windowMs = (n) => {
    const i = at(n.key)
    const start = n.from ?? i
    let ms = 0
    for (let k = start; k <= i; k++) ms += durs[k] || 1200
    return ms
  }
  const next = spot >= 0 ? FLOW[spot + 1] : null

  return (
    <div className="af">
      <div className="af-h">
        <div><b>Autonomous agent team</b><span>One agent works at a time, then hands over to the next</span></div>
        <div className="af-chips">
          <i>{doneN}/{FLOW.length} done</i>
          <i className={escalated ? 'esc' : 'auto'}>{escalated ? '1 human handoff' : '0 humans in the loop'}</i>
          {done && <i>{(totalMs / 1000).toFixed(1)}s</i>}
        </div>
      </div>

      {/* relay: who has finished, who is working, who is next */}
      <div className="rl">
        {FLOW.map((n, k) => {
          const st = states[k]
          return (
            <React.Fragment key={n.id}>
              <div className={`rl-n ${st} t-${n.tone}`}>
                <Avatar n={n} size={38} />
                <span className="rl-tick"><I.Check size={9} /></span>
                <em>{n.short}</em>
              </div>
              {k < FLOW.length - 1 && (
                <div className={`rl-l ${states[k] === 'done' ? 'on' : ''} ${states[k] === 'done' && states[k + 1] !== 'done' && !done ? 'go' : ''} t-${n.tone}`}><i /></div>
              )}
            </React.Fragment>
          )
        })}
      </div>

      {/* spotlight: the one agent that is working right now */}
      {spot >= 0 && (() => {
        const n = FLOW[spot]
        const win = windowMs(n)
        return (
          <div className={`sp work t-${n.tone}`} key={n.id} style={{ '--win': win + 'ms' }}>
            <div className="sp-head">
              <div className="sp-av"><Avatar n={n} size={58} /></div>
              <div className="sp-id">
                <span>{n.side}</span>
                <b>{n.name}</b>
                <em>{n.role}</em>
              </div>
              <span className="sp-state">Working<span className="af-dots"><i /><i /><i /></span></span>
            </div>
            <div className="sp-now">{spot > 0 && FLOW[spot - 1].link && <span className="af-recv">Received · {FLOW[spot - 1].link}</span>}{n.now}…</div>
            <ul className="sp-tasks">
              {n.tasks.map((t, i) => (
                <li key={t} style={{ '--i': i, '--n': n.tasks.length }}>
                  <span className="sp-ic"><i className="spin" /><b><I.Check size={11} /></b></span>
                  <span className="sp-tx">{t}</span>
                </li>
              ))}
            </ul>
            <div className="sp-tools">{n.tools.map((t, i) => <span key={t} style={{ '--i': i }}>{t}</span>)}</div>
            {next && n.link && <div className="sp-hand">Handing over to <b>{next.name}</b><em>{n.link}</em><span className="sp-arrow">→</span></div>}
            <div className="sp-bar"><i /></div>
          </div>
        )
      })()}

      {spot < 0 && done && (
        <div className="sp fin">
          <div className="fin-ic"><I.Check size={26} /></div>
          <div><b>{escalated ? 'Handed to a human' : 'All six agents finished on their own'}</b><span>{FLOW.length} steps · {(totalMs / 1000).toFixed(1)}s · {escalated ? 'a person takes it from here' : 'no human needed'}</span></div>
        </div>
      )}
      {spot < 0 && !done && lastDone >= 0 && <div className="sp wait"><span>Passing the baton…</span></div>}

      {/* completed work, newest first */}
      {doneN > 0 && (
        <div className="hist">
          <div className="hist-h">Completed work</div>
          {FLOW.map((n, k) => ({ n, k })).filter(({ k }) => states[k] === 'done').reverse().map(({ n }) => {
            const s = get(n.key)
            return (
              <div key={n.id} className={`hist-r t-${n.tone} ${s?.tone || ''}`}>
                <Avatar n={n} size={30} />
                <div><b>{n.name}</b><span>{resultOf(n)}</span></div>
                <i className="hist-tick"><I.Check size={11} /></i>
              </div>
            )
          })}
        </div>
      )}
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
