import React from 'react'
import { I } from './icons.jsx'

const AGENTS = [
  { key: 'intelligence', name: 'Intelligence', ic: '🧠' },
  { key: 'risk', name: 'Risk', ic: '🛡️' },
  { key: 'resolution', name: 'Resolution', ic: '🧩' },
  { key: 'ledger', name: 'Ledger Ops', ic: '📒' },
]

export default function Center({ run, reveal }) {
  const steps = run?.steps || []
  const shown = (key) => steps.findIndex((s) => s.key === key) < reveal && steps.findIndex((s) => s.key === key) >= 0
  const get = (key) => steps.find((s) => s.key === key)
  const done = run && reveal >= steps.length
  const activeIdx = AGENTS.findIndex((a) => !shown(a.key))
  const consent = get('consent'), ev = get('eval'), disp = get('dispatch')

  return (
    <div className="col center">
      <div className="col-h">
        <div><b>Live Orchestration & Decision Trace</b><div className="muted xs">Merchant Buddy ⇄ Paytm 4-Agent Mesh</div></div>
        <span className={`state ${run ? (done ? 'done' : 'run') : ''}`}>{run ? (done ? 'Resolved' : 'Running…') : 'Idle'}</span>
      </div>

      {run && <div className="utter"><span className="muted xs">Merchant said</span><div>“{run.utterance}”</div><span className="chip-i">{run.sc.intent}</span></div>}

      <div className="mesh">
        {AGENTS.map((a, k) => {
          const on = shown(a.key), act = run && !done && on === false && k === activeIdx && reveal >= 4
          return (
            <React.Fragment key={a.key}>
              <div className={`node ${on ? 'on' : ''} ${act ? 'act' : ''} ${on && get(a.key)?.tone === 'bad' ? 'bad' : ''} ${on && get(a.key)?.tone === 'warn' ? 'warn' : ''}`}>
                <span className="n-ic">{a.ic}</span><b>{a.name}</b>
                <span className="n-s">{on ? `${get(a.key).ms}ms ✓` : act ? '…' : 'idle'}</span>
              </div>
              {k < 3 && <span className={`arrow ${on ? 'on' : ''}`}>→</span>}
            </React.Fragment>
          )
        })}
      </div>

      {!run && (
        <div className="empty">
          <I.Spark size={28} />
          <b>Waiting for a merchant request</b>
          <span className="muted sm">Tap a quick scenario on the phone, upload a PoD / screenshot, or type in Hinglish. The decision trace appears here live.</span>
        </div>
      )}

      {shown('consent') && consent && (
        <div className="tcard in">
          <div className="t-h"><span className="ok-dot"><I.Check size={12} /></span><b>DPDP consent verified</b><span className="muted xs">by Paytm Risk Agent</span></div>
          <div className="kv">
            <span>Token</span><code>{consent.consent.token}</code>
            <span>Purpose</span><code>{consent.consent.purpose}</code>
            <span>Scope</span><code>{consent.consent.scope}</code>
            <span>Issued · TTL</span><code>{consent.consent.issued} · {consent.consent.ttl_min} min</code>
          </div>
        </div>
      )}

      {shown('eval') && ev && (
        <div className="tcard in">
          <div className="t-h"><b>Merchant Buddy · Intervention evaluation</b><span className="chip-i sel">Selected {ev.selected}</span></div>
          {ev.options.map((o) => (
            <div key={o.id} className={`opt ${o.id === ev.selected ? 'sel' : ''}`}>
              <span className="o-id">{o.id}</span>
              <div className="o-mid"><div className="o-l">{o.label}</div><div className="muted xs">{o.why}</div><div className="o-bar"><i style={{ width: o.score + '%' }} /></div></div>
              <span className="o-sc">{o.score}</span>
            </div>
          ))}
        </div>
      )}

      {shown('dispatch') && disp && (
        <div className="tcard in">
          <div className="t-h"><b>A2A dispatch</b><span className="muted xs">:8003 → :8002 /a2a/dispatch</span></div>
          <div className="json">
            <div><span className="muted xs">REQUEST</span><pre>{JSON.stringify(disp.request, null, 1)}</pre></div>
            <div><span className="muted xs">RESPONSE</span><pre>{JSON.stringify(disp.response, null, 1)}</pre></div>
          </div>
        </div>
      )}

      {AGENTS.some((a) => shown(a.key)) && (
        <div className="tcard in">
          <div className="t-h"><b>Paytm sub-agents</b><span className="muted xs">Intelligence → Risk → Resolution → Ledger Ops</span></div>
          {AGENTS.filter((a) => shown(a.key)).map((a) => {
            const s = get(a.key)
            return (
              <div key={a.key} className={`ag ${s.tone || ''}`}>
                <span className="ag-ic">{a.ic}</span>
                <div><b>{a.name}</b><div className="sm">{s.say}</div></div>
                <span className="muted xs">{s.ms}ms</span>
              </div>
            )
          })}
        </div>
      )}

      {shown('reply') && (
        <div className={`tcard in reply ${get('reply').tone || ''}`}>
          <div className="t-h"><b>Reply to merchant</b><span className="muted xs">Hinglish · TTS-ready</span></div>
          <div className="sm">{get('reply').reply}</div>
        </div>
      )}
    </div>
  )
}
