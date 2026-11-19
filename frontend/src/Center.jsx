import React, { useEffect, useRef, useState } from 'react'
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


/* ---------- Parent agent + chosen specialist: a relay, one agent in the spotlight at a time ---------- */
const ico = (children, s = 22) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
const ICONS = {
  consent: <><rect x="5" y="10.5" width="14" height="9.5" rx="2.4" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /><path d="M9.6 15.2l1.7 1.7 3.2-3.4" /></>,
  intelligence: <><circle cx="6" cy="7" r="2.1" /><circle cx="18" cy="7" r="2.1" /><circle cx="12" cy="17.5" r="2.1" /><path d="M7.7 8.4l3 7.4M16.3 8.4l-3 7.4M8.2 7h7.6" /></>,
  risk: <><path d="M12 3.2l7 2.8v5.4c0 4.4-2.9 7.6-7 9.4-4.1-1.8-7-5-7-9.4V6z" /><path d="M9.2 12l2.1 2.1 3.6-3.8" /></>,
  resolution: <><circle cx="6" cy="6" r="2.1" /><circle cx="6" cy="18" r="2.1" /><circle cx="18" cy="12" r="2.1" /><path d="M8 6h3a3 3 0 0 1 3 3v0M8 18h3a3 3 0 0 0 3-3v0M14 12h2" /></>,
  ledger: <><path d="M6 4.5h10.5A1.5 1.5 0 0 1 18 6v13.5H7.5A1.5 1.5 0 0 1 6 18z" /><path d="M9.5 9h5M9.5 12.5h5M9.5 16h3" /></>,
}
const TEAM = [
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

// The parent agent (Merchant Buddy) reads the request, picks ONE specialist, waits for the answer and then acts on the app.
const LEAD = {
  intelligence: ['SETTLEMENT_RECONCILE', 'DUPLICATE_RECONCILE', 'FEE_GST_LOAN', 'GROWTH_ADVISORY'],
  risk: ['UTR_VERIFY', 'SETTLEMENT_HOLD_BANK', 'BANK_KYC_UPDATE'],
  resolution: ['CHARGEBACK_RESOLVE', 'REFUND_MANAGE', 'MANDATE_TROUBLESHOOT', 'CASHFLOW_EDI_SWITCH', 'SOUNDBOX_RETURN', 'LOAN_CLOSURE_NOC', 'ESCALATE_HUMAN'],
}
// Merchant-side child agents (they work for the Merchant Buddy) and Paytm-side child agents (they work for the Paytm AI Agent).
const MKIDS = [
  { id: 'memory', glyph: 'memory', key: 'insight', name: 'Memory Agent', short: 'Memory', side: 'Merchant side', role: 'Remembers what happened before', tone: 'indigo', link: 'History',
    now: 'Recalling this merchant’s past cases', tasks: ['Searching the merchant’s past cases', 'Picking out what is relevant now'], tools: ['Strategy memory', 'History'] },
  { id: 'intent', glyph: 'intent', key: 'eval', name: 'Intent & Options Agent', short: 'Intent', side: 'Merchant side', role: 'Understands the request and compares options', tone: 'blue', link: 'Decision',
    now: 'Understanding the request and scoring options', tasks: ['Understanding what the merchant said', 'Scoring options A, B and C', 'Picking the best action'], tools: ['Intent router', 'Option scorer'] },
  { id: 'consent', key: 'consent', name: 'DPDP Consent Gate', short: 'Consent', side: 'Merchant side', role: 'Nothing is shared without permission', tone: 'teal', link: 'Signed request',
    now: 'Making sure the merchant allowed this', tasks: ['Minting a consent token', 'Checking purpose and scope', 'Signing the request for Paytm'], tools: ['DPDP ledger', 'Token service'] },
]
const MPARENT = { id: 'buddy', key: 'input', name: 'Merchant Buddy (parent)', short: 'Buddy', side: 'Merchant side', role: 'Parent agent: hears the merchant and runs the merchant-side team', tone: 'blue', link: 'Request', brand: true,
  now: 'Listening and deciding who to involve', tasks: ['Hearing what the merchant said', 'Handing the work to its own helpers', 'Preparing the request for Paytm'], tools: ['Voice', 'Helpers'] }
const SUPPORT = {
  REFUND_MANAGE: ['risk'], CHARGEBACK_RESOLVE: ['risk'], MANDATE_TROUBLESHOOT: ['risk'], LOAN_CLOSURE_NOC: ['risk'],
  CASHFLOW_EDI_SWITCH: ['intelligence'], SETTLEMENT_HOLD_BANK: ['intelligence'], DUPLICATE_RECONCILE: ['resolution'],
}
const KIDS = ['intelligence', 'risk', 'resolution', 'ledger']
const PAYTM = { id: 'paytm', pt: true, key: 'dispatch', name: 'Paytm AI Agent (parent)', short: 'Paytm', side: 'Paytm side', role: 'Parent agent: receives the request and picks the right specialist', tone: 'sky', link: 'Picks a specialist',
  now: 'Reading the request and choosing the specialist', tasks: ['Receiving the signed request', 'Verifying the consent token', 'Deciding which specialist handles it'], tools: ['A2A endpoint', 'Specialist router'] }

// Builds the run plan: which agents are used for this request, in what order, and what state each is in.
function plan(run, reveal) {
  const intent = run?.sc?.intent
  const steps = run?.steps || []
  const lead = Object.keys(LEAD).find((k) => LEAD[k].includes(intent)) || 'resolution'
  const support = SUPPORT[intent] || []
  const idx = (k) => steps.findIndex((s) => s.key === k)
  const used = (id) => id === 'ledger' || id === lead || support.includes(id)
  const role = (id) => (id === lead ? 'lead' : support.includes(id) ? 'support' : id === 'consent' ? 'gate' : 'ops')
  const kid = (id) => ({ ...TEAM.find((a) => a.id === id), key: id, role2: role(id) })
  const seq = [
    { ...MPARENT, uid: 'buddy-1' },
    ...MKIDS.filter((m) => idx(m.key) >= 0),
    { ...PAYTM },
    ...KIDS.filter(used).map(kid),
    { ...MPARENT, key: 'reply', uid: 'buddy-2', art: 'buddy', link: '', role: 'Parent agent: takes the answer and updates the app', now: 'Turning the answer into a reply and updating the app', tasks: ['Receiving the answer from Paytm', 'Updating the ledger and the app', 'Speaking the reply to the merchant'], tools: ['Voice reply', 'App state'] },
  ]
  // each used agent works from its own step until the next used agent's step (skipped agents' time is absorbed)
  seq.forEach((n, k) => {
    const own = idx(n.key)
    const nextOwn = k < seq.length - 1 ? idx(seq[k + 1].key) : own
    n.start = k === 0 ? 0 : Math.max(own, 0)
    n.end = k === seq.length - 1 ? Math.max(own, 0) : Math.max(nextOwn - 1, n.start)
  })
  const stOf = (n) => (idx(n.key) < 0 ? 'idle' : reveal > n.end ? 'done' : reveal >= n.start ? 'work' : 'idle')
  const states = seq.map(stOf)
  const byId = {}
  seq.forEach((n, k) => { byId[n.uid === 'buddy-2' ? 'buddy2' : n.id] = states[k] })
  const allIds = new Set([...seq.map((n) => n.id)])
  return { seq, states, byId, lead, support, usedCount: allIds.size, role }
}

// Cyberpunk cartoon AI faces: one character per agent (skin, neon hair/gear, expression).
const INK = '#0a0f2c'
const FACE = 'M9.5 17.5c0-7 4.6-12 10.5-12s10.5 5 10.5 12v6.5c0 5.4-4.4 10.2-10.5 10.2S9.5 29.4 9.5 24z'
const SKIN = { buddy: '#ffd2b8', consent: '#bfe9f6', intelligence: '#e4d3ff', risk: '#ffc3dd', resolution: '#ffdca3', ledger: '#cfe0ff' }

function Robot({ id, size }) {
  const sk = SKIN[id]
  // eyes (whites + neon pupils); each character tweaks size / shape
  const Eyes = ({ ry = 3.5, brow = null, cyber = false }) => (
    <g>
      <g className="rb-lid">
        <ellipse cx="15.2" cy="20.6" rx="3.1" ry={ry} fill="#fff" stroke={INK} strokeWidth=".9" />
        {cyber ? <rect className="rb-fill" x="21.2" y="18.6" width="7.2" height="4" rx="2" /> : <ellipse cx="24.8" cy="20.6" rx="3.1" ry={ry} fill="#fff" stroke={INK} strokeWidth=".9" />}
      </g>
      <circle className="rb-eye rb-pupil" cx="15.6" cy="21" r="1.9" />
      {!cyber && <circle className="rb-eye rb-pupil" cx="24.4" cy="21" r="1.9" />}
      <circle cx="16.2" cy="20.2" r=".6" fill="#fff" /><circle cx="25" cy="20.2" r=".6" fill="#fff" opacity={cyber ? 0 : 1} />
      {brow}
    </g>
  )
  const smile = (d, extra = {}) => <path className="rb-mouth" d={d} fill="none" stroke={INK} strokeWidth="1.3" strokeLinecap="round" {...extra} />
  const ear = (neon = true) => <><circle className={neon ? 'rb-fill rb-ear' : ''} cx="8.6" cy="21" r="1.7" fill={neon ? undefined : sk} stroke={INK} strokeWidth=".8" /><circle className={neon ? 'rb-fill rb-ear' : ''} cx="31.4" cy="21" r="1.7" fill={neon ? undefined : sk} stroke={INK} strokeWidth=".8" /></>

  const art = {
    // friendly host: spiky neon hair + headset
    buddy: (
      <>
        <path className="rb-fill rb-hair" d="M9.2 16L10.6 7.4 14.4 11 17 4.6 20 10 23 4.6 25.6 11 29.4 7.4 30.8 16Q20 9.6 9.2 16z" stroke={INK} strokeWidth="1.1" strokeLinejoin="round" />
        <path d={FACE} fill={sk} stroke={INK} strokeWidth="1.4" />
        <path className="rb-hair" d="M9.4 15.6Q20 9.2 30.6 15.6" fill="none" stroke={INK} strokeWidth="0" />
        <path className="rb-neon" d="M8 19a12 12 0 0 1 24 0" fill="none" strokeWidth="1.8" strokeLinecap="round" /><rect x="6.6" y="18.5" width="3.2" height="6" rx="1.5" fill="#141a40" stroke="var(--neon)" strokeWidth=".9" /><rect x="30.2" y="18.5" width="3.2" height="6" rx="1.5" fill="#141a40" stroke="var(--neon)" strokeWidth=".9" />
        <path className="rb-neon" d="M32 24.5v3.2l-4 1.8" fill="none" strokeWidth="1.2" strokeLinecap="round" /><circle className="rb-fill" cx="27.6" cy="29.5" r="1.3" />
        <Eyes ry={3.7} />
        {smile('M15.6 27c2.4 3.2 6.4 3.2 8.8 0')}
        <ellipse cx="12" cy="25.4" rx="1.9" ry="1.1" fill="#ff7aa8" opacity=".35" /><ellipse cx="28" cy="25.4" rx="1.9" ry="1.1" fill="#ff7aa8" opacity=".35" />
      </>
    ),
    // stern gatekeeper: helmet with lock emblem
    consent: (
      <>
        <path d={FACE} fill={sk} stroke={INK} strokeWidth="1.4" />
        <path d="M9.2 18v-1.4c0-7 4.4-11.8 10.8-11.8s10.8 4.8 10.8 11.8V18c-4-1.6-7-2.4-10.8-2.4S13.2 16.4 9.2 18z" fill="#12d6a8" stroke={INK} strokeWidth="1.4" strokeLinejoin="round" />
        <rect x="17" y="8.6" width="6" height="5" rx="1.4" fill="#06231f" stroke={INK} strokeWidth=".8" /><path d="M18.6 8.6v-1a1.4 1.4 0 0 1 2.8 0v1" fill="none" stroke="#06231f" strokeWidth="1" />
        <path className="rb-neon" d="M9.6 17.6c3.6-1.4 6.8-2.1 10.4-2.1s6.8.7 10.4 2.1" fill="none" strokeWidth="1" opacity=".8" />
        <Eyes ry={2.6} brow={<g stroke={INK} strokeWidth="1.2" strokeLinecap="round"><path d="M11.6 17.4l7 1.3M28.4 17.4l-7 1.3" /></g>} />
        {smile('M16.8 28h6.4')}
        {ear(true)}
      </>
    ),
    // genius: swoosh hair + big neon goggles + circuit temple
    intelligence: (
      <>
        <path className="rb-fill rb-hair" d="M9.2 17C9.6 9.6 14.4 5 20.6 5 27 5 30.8 9.6 30.8 17c-3.4-3.8-8.8-5-13.6-3.8-3 .8-5.6 2.2-8 3.8z" stroke={INK} strokeWidth="1.2" strokeLinejoin="round" />
        <path d={FACE} fill={sk} stroke={INK} strokeWidth="1.4" />
        <path className="rb-fill rb-hair" d="M9.4 16.6C10 9.8 14.6 5.4 20.6 5.4c5.8 0 9.6 4.4 10 11.2-3.2-3.4-8.4-4.6-13-3.4-3 .8-5.6 2-8.2 3.4z" stroke={INK} strokeWidth="1.1" strokeLinejoin="round" />
        <circle cx="15" cy="20.8" r="5.4" fill="#050819" stroke="var(--neon)" strokeWidth="1.5" /><circle cx="25" cy="20.8" r="5.4" fill="#050819" stroke="var(--neon)" strokeWidth="1.5" /><path d="M20.2 20.2h-0.4" stroke="var(--neon)" strokeWidth="1.5" /><path className="rb-neon" d="M9.6 19.8H8M31 19.8h1.6" strokeWidth="1.2" />
        <circle className="rb-eye rb-pupil" cx="15.4" cy="21" r="2.3" /><circle className="rb-eye rb-pupil" cx="24.6" cy="21" r="2.3" />
        <circle cx="16.3" cy="20" r=".7" fill="#fff" /><circle cx="25.5" cy="20" r=".7" fill="#fff" />
        <path className="rb-neon rb-circ" d="M30.6 22.6h-2.4v2.2h-2" fill="none" strokeWidth=".9" strokeLinecap="round" />
        {smile('M16.4 28c3 2.6 7 1.4 8.4-1')}
      </>
    ),
    // punk risk officer: mohawk + scanner eye + scar
    risk: (
      <>
        <path className="rb-fill rb-hair" d="M16.6 12.4 17.2 2.8 19 7.2 20 1.8 21 7.2 22.8 2.8 23.4 12.4z" stroke={INK} strokeWidth="1.1" strokeLinejoin="round" />
        <path d={FACE} fill={sk} stroke={INK} strokeWidth="1.4" />
        <path d="M9.6 15.4c1.6-4 5.4-6.6 10.4-6.6s8.8 2.6 10.4 6.6c-3.2-2-6.6-3-10.4-3s-7.2 1-10.4 3z" fill="#1a1236" stroke={INK} strokeWidth="1" />
        <path className="rb-fill rb-hair" d="M18.6 9.2l1.4-4.6 1.4 4.6z" />
        <Eyes ry={3.4} cyber brow={<g stroke={INK} strokeWidth="1.3" strokeLinecap="round"><path d="M11.4 17.2l7.2 1.4" /><path d="M21.4 17.4l7.4-1.8" /></g>} />
        <rect className="rb-neon rb-scan" x="21" y="18.2" width="7.6" height="4.8" rx="2.4" fill="none" strokeWidth="1.1" />
        <path d="M27.4 16.4l2.4 7.2" stroke="#ff2f76" strokeWidth="1.1" strokeLinecap="round" /><path d="M26.4 19.4l2.6.6M27 21.6l2.4.6" stroke="#ff2f76" strokeWidth=".8" strokeLinecap="round" />
        {smile('M16 27.4c2.2 1.8 5.6 1.8 8.4-.6')}
        <circle className="rb-fill rb-ear" cx="8.6" cy="22.6" r="1.4" /><circle className="rb-fill rb-ear" cx="31.4" cy="22.6" r="1.4" />
      </>
    ),
    // engineer: hard hat with pushed-up goggles, confident grin
    resolution: (
      <>
        <path d={FACE} fill={sk} stroke={INK} strokeWidth="1.4" />
        <path d="M8.6 16.6C8.6 9 13.4 4.4 20 4.4S31.4 9 31.4 16.6z" fill="#ffb23d" stroke={INK} strokeWidth="1.4" strokeLinejoin="round" />
        <rect x="7" y="15.4" width="26" height="3" rx="1.5" fill="#ff8f1f" stroke={INK} strokeWidth="1.1" />
        <path d="M17 5v10M23 5v10" stroke={INK} strokeWidth=".8" opacity=".5" /><circle className="rb-fill" cx="20" cy="9.2" r="1.7" />
        <circle cx="14" cy="14.2" r="2.7" fill="#0a0f2c" stroke="var(--neon)" strokeWidth="1.1" /><circle cx="26" cy="14.2" r="2.7" fill="#0a0f2c" stroke="var(--neon)" strokeWidth="1.1" />
        <Eyes ry={3.1} brow={<g stroke={INK} strokeWidth="1.3" strokeLinecap="round"><path d="M11.8 18.6l6-.6M28.2 18.6l-6-.6" /></g>} />
        <path d="M15.2 26.2h9.6a4.8 4.8 0 0 1-9.6 0z" fill="#fff" stroke={INK} strokeWidth="1.2" strokeLinejoin="round" /><path d="M20 26.4v4" stroke={INK} strokeWidth=".6" />
        {ear(true)}
      </>
    ),
    // accountant: side-parted hair, square glasses, number ticker on cheek
    ledger: (
      <>
        <path className="rb-fill rb-hair" d="M9.2 17.2C9.6 9.4 14.2 5 20.4 5c6.2 0 10 4.2 10.4 12.2-3.8-3.4-9-4.2-13.6-2-3 1.4-5.2 2.6-8 2z" stroke={INK} strokeWidth="1.2" strokeLinejoin="round" />
        <path d={FACE} fill={sk} stroke={INK} strokeWidth="1.4" />
        <path className="rb-fill rb-hair" d="M9.4 16.8C9.8 9.8 14.4 5.5 20.4 5.5c5.8 0 9.4 4 10 11.1-3.6-3-8.8-3.6-13-1.6-2.8 1.2-5.2 2.4-8 1.8z" stroke={INK} strokeWidth="1.1" strokeLinejoin="round" />
        <rect x="10.2" y="17.4" width="9" height="7" rx="2.2" fill="#050819" stroke="var(--neon)" strokeWidth="1.4" /><rect x="20.8" y="17.4" width="9" height="7" rx="2.2" fill="#050819" stroke="var(--neon)" strokeWidth="1.4" /><path className="rb-neon" d="M19.2 20.4h1.6M10.2 19H8.6M29.8 19h1.6" strokeWidth="1.2" />
        <rect className="rb-eye rb-pupil" x="13" y="19.4" width="3.8" height="3.4" rx="1" /><rect className="rb-eye rb-pupil" x="23.2" y="19.4" width="3.8" height="3.4" rx="1" />
        <path className="rb-neon rb-circ" d="M26.6 28.4h2.6M27.6 30.2h2" strokeWidth="1" strokeLinecap="round" />
        {smile('M17 28.4h6.2')}
      </>
    ),
  }[id]
  return (
    <svg className={`rb rb-${id}`} viewBox="0 0 40 40" width={size} height={size} aria-hidden="true">
      <path className="rb-body" d="M10.4 39.6c.8-3.6 4.6-5.8 9.6-5.8s8.8 2.2 9.6 5.8z" />
      <path className="rb-neon" d="M14.6 37.4h10.8" strokeWidth="1" strokeLinecap="round" opacity=".85" />
      <rect x="16.6" y="31.6" width="6.8" height="4" rx="1.6" fill={sk} stroke={INK} strokeWidth="1" />
      {art}
    </svg>
  )
}

function Avatar({ n, size = 44 }) {
  if (n.glyph) return <div className="ag-av" style={{ '--s': size + 'px' }}><span className="pt-av gl" style={{ width: size * .94, height: size * .94 }}>{ico(n.glyph === 'memory' ? <><ellipse cx="12" cy="6" rx="7" ry="2.8" /><path d="M5 6v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6" /><path d="M5 12v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-6" /></> : <><path d="M5 5h14a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 16h-7l-4.5 3.5V16H5a1.5 1.5 0 0 1-1.5-1.5v-8A1.5 1.5 0 0 1 5 5z" /><path d="M8 9.5h8M8 12.3h5" /></>, Math.round(size * .5))}</span></div>
  if (n.pt) return <div className="ag-av" style={{ '--s': size + 'px' }}><span className="pt-av" style={{ width: size * .94, height: size * .94, fontSize: size * .3 }}><b>pay</b><i>tm</i></span></div>
  return (
    <div className="ag-av" style={{ '--s': size + 'px' }}>
      <Robot id={n.art || n.id} size={Math.round(size * 0.94)} />
    </div>
  )
}

function AgentFlow({ run, reveal, done, escalated, totalMs }) {
  const P = plan(run, reveal)
  const FLOW = P.seq, states = P.states
  const steps = run.steps
  const durs = run.durs || []
  const get = (key) => steps.find((s) => s.key === key)
  const doneN = states.filter((s) => s === 'done').length
  const spot = states.findIndex((s) => s === 'work')
  const lastDone = states.lastIndexOf('done')
  const lead = TEAM.find((a) => a.id === P.lead)
  const resultOf = (n) => {
    const s = get(n.key)
    if (!s) return ''
    if (n.key === 'reply') return 'Reply spoken · app and ledger updated'
    if (n.key === 'input') return 'Passed the request to its helpers'
    if (n.key === 'insight') return s.insight?.summary || 'Found relevant history'
    if (n.key === 'eval') {
      if (s.options) { const o = s.options.find((x) => x.id === s.selected); return `Option ${s.selected}: ${o ? o.label : ''}` }
      return `Understood: ${s.route?.intent || 'the request'}`
    }
    if (n.id === 'consent') return `Token ${s.consent.token.slice(0, 18)}… · ${s.consent.purpose.replace(/_/g, ' ')}`
    if (n.id === 'paytm') return `Picked ${lead.name}${P.support.length ? ' + ' + P.support.map((x) => TEAM.find((a) => a.id === x).name).join(', ') + ' to help' : ''}`
    return s.say
  }
  const windowMs = (n) => { let ms = 0; for (let k = n.start; k <= n.end; k++) ms += durs[k] || 1200; return ms }
  const next = spot >= 0 ? FLOW[spot + 1] : null
  const anySpec = KIDS.some((id) => P.byId[id] === 'work')
  const mSt = P.byId.buddy === 'work' || P.byId.buddy2 === 'work' ? 'work' : P.byId.buddy2 === 'done' ? 'done' : P.byId.buddy === 'done' ? 'wait' : 'idle'
  const pSt = P.byId.paytm === 'work' ? 'work' : anySpec ? 'wait' : P.byId.buddy2 === 'done' || (P.byId.paytm === 'done' && !anySpec && P.byId.ledger === 'done') ? 'done' : P.byId.paytm === 'done' ? 'wait' : 'idle'
  const stateOfId = (id) => {
    const k = FLOW.findIndex((n) => n.id === id && n.key !== 'reply')
    return k < 0 ? 'standby' : states[k]
  }
  const lbl = { work: 'Working', wait: 'Waiting for helpers', done: 'Done', idle: 'Ready' }
  const Kid = ({ n, sub }) => {
    const st = stateOfId(n.id)
    return (
      <div className={`tr-k ${st} t-${n.tone}`}>
        <i className="tr-up" />
        <Avatar n={n} size={40} />
        <b>{n.short === 'Intel' ? 'Intelligence' : n.short === 'Fix' ? 'Resolution' : n.short}</b>
        <em>{st === 'standby' ? 'Standing by' : sub}</em>
        <span className="tr-tick"><I.Check size={9} /></span>
      </div>
    )
  }

  return (
    <div className="af">
      <div className="af-h">
        <div><b>Agent tree</b><span>Each side has a parent and its helpers. Only the needed ones work</span></div>
        <div className="af-chips">
          <i>{P.usedCount} of 9 agents used</i>
          <i className={escalated ? 'esc' : 'auto'}>{escalated ? '1 human handoff' : '0 humans in the loop'}</i>
          {done && <i>{(totalMs / 1000).toFixed(1)}s</i>}
        </div>
      </div>

      {/* two teams: each has a parent agent (centred) with its own child agents (centred) below */}
      <div className="tr">
        <div className="tr-team">
          <div className="tr-lab">Merchant side</div>
          <div className={`tr-root ${mSt} t-blue`}>
            <Avatar n={TEAM.find((a) => a.id === 'buddy')} size={46} />
            <b>Merchant Buddy</b><em>Parent agent</em>
            <span className="tr-st">{lbl[mSt]}</span>
          </div>
          <div className="tr-stem" />
          <div className="tr-kids c3">
            {MKIDS.map((n) => <Kid key={n.id} n={n} sub={n.id === 'consent' ? 'Asks permission' : n.id === 'memory' ? 'Recalls history' : 'Understands & decides'} />)}
          </div>
        </div>

        <div className={`tr-link ${P.byId.consent === 'done' ? 'done' : P.byId.consent === 'work' ? 'work' : ''}`}>
          <i className="tr-wire" /><span>Signed request goes to Paytm · answer comes back</span><i className="tr-wire" />
        </div>

        <div className="tr-team pt">
          <div className="tr-lab">Paytm side</div>
          <div className={`tr-root pt ${pSt} t-sky`}>
            <Avatar n={FLOW.find((n) => n.id === 'paytm')} size={46} />
            <b>Paytm AI Agent</b><em>Parent agent</em>
            <span className="tr-st">{pSt === 'work' ? 'Choosing specialist' : lbl[pSt]}</span>
          </div>
          <div className="tr-stem" />
          <div className="tr-kids c4">
            {KIDS.map((id) => {
              const n = TEAM.find((a) => a.id === id)
              const r = P.role(id)
              return <Kid key={id} n={n} sub={r === 'lead' ? 'Chosen specialist' : r === 'support' ? 'Called in to help' : 'Writes the books'} />
            })}
          </div>
        </div>
      </div>

      {/* spotlight: the one agent that is working right now */}
      {spot >= 0 && (() => {
        const n = FLOW[spot]
        const win = windowMs(n)
        return (
          <div className={`sp work t-${n.tone}`} key={n.uid || n.id} style={{ '--win': win + 'ms' }}>
            <div className="sp-head">
              <div className="sp-av"><Avatar n={n} size={58} /></div>
              <div className="sp-id">
                <span>{n.side}{n.role2 === 'support' ? ' · called in to help' : n.role2 === 'lead' ? ' · lead specialist' : ''}</span>
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
            {next && <div className="sp-hand">Hands the result back, next: <b>{next.key === 'reply' ? 'Merchant Buddy' : next.name}</b>{n.link && <em>{n.link}</em>}<span className="sp-arrow">→</span></div>}
            <div className="sp-bar"><i /></div>
          </div>
        )
      })()}

      {spot < 0 && done && (
        <div className="sp fin">
          <div className="fin-ic"><I.Check size={26} /></div>
          <div><b>{escalated ? 'Handed to a human' : 'Solved by the parent and its team'}</b><span>{P.usedCount} of 9 agents used · {(totalMs / 1000).toFixed(1)}s · {escalated ? 'a person takes it from here' : 'no human needed'}</span></div>
        </div>
      )}
      {spot < 0 && !done && lastDone >= 0 && <div className="sp wait"><span>Passing the baton…</span></div>}

      {doneN > 0 && (
        <div className="hist">
          <div className="hist-h">Completed work</div>
          {FLOW.map((n, k) => ({ n, k })).filter(({ k }) => states[k] === 'done').reverse().map(({ n }) => {
            const s = get(n.key)
            return (
              <div key={n.uid || n.id} className={`hist-r t-${n.tone} ${s?.tone || ''}`}>
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

// Collapsible section: header always visible, body opens on click (or automatically when it becomes relevant).
function Section({ title, sub, badge, tone, open, onToggle, children }) {
  return (
    <div className={`acc ${open ? 'open' : ''} ${tone || ''}`}>
      <button className="acc-h" onClick={onToggle} aria-expanded={open}>
        <span className="acc-t"><b>{title}</b><em>{sub}</em></span>
        {badge && <i className="acc-b">{badge}</i>}
        <span className="acc-chev">›</span>
      </button>
      <div className="acc-body"><div>{children}</div></div>
    </div>
  )
}

function flowInfo(run, reveal) {
  const P = plan(run, reveal)
  return { FLOW: P.seq, P, states: P.states, doneN: P.states.filter((s) => s === 'done').length, cur: P.states.findIndex((s) => s === 'work') }
}

export default function Center({ run, reveal, busy, onTry, demoActive }) {
  const [tech, setTech] = useState(false)
  const [openSet, setOpenSet] = useState({})
  const pinned = useRef(false)
  const steps = run?.steps || []
  const idx = (key) => steps.findIndex((s) => s.key === key)
  const shown = (key) => idx(key) >= 0 && idx(key) < reveal
  const get = (key) => steps.find((s) => s.key === key)
  const done = run && reveal >= steps.length
  const cur = run && reveal > 0 ? steps[Math.min(reveal, steps.length) - 1] : null
  const stageNow = run ? STAGES.findIndex((st) => st.keys.includes(cur?.key)) : -1
  const ev = get('eval'), disp = get('dispatch'), ins = get('insight')
  const escalated = run?.live ? !!run.escalated : ev && ev.selected === 'C' && shown('eval')
  const awaiting = shown('reply') && !!get('reply')?.confirm
  const totalMs = run?.live ? run.elapsed || 0 : steps.reduce((a, s) => a + (s.ms || 0), 0)

  // A new run starts with the agent team open; sections open by themselves when they become relevant,
  // and everything folds away once the answer is ready. Clicking a section takes over for that run.
  useEffect(() => { pinned.current = false; setOpenSet(run ? { agents: true } : {}) }, [run])
  useEffect(() => {
    if (!run || pinned.current) return
    if (shown('reply')) setOpenSet({ result: true })
    else if (shown('eval')) setOpenSet({ agents: true, decision: true })
  }, [reveal, run])
  const toggle = (k) => { pinned.current = true; setOpenSet((s) => ({ ...s, [k]: !s[k] })) }

  const fi = run ? flowInfo(run, reveal) : null
  const FLOW = fi ? fi.FLOW : []
  const resBadge = run && shown('reply') ? (get('reply').tone === 'bad' ? 'Fraud blocked' : awaiting ? 'Needs your OK' : escalated ? 'Human handoff' : 'Resolved by AI') : ''
  const sections = run ? [
    { k: 'agents', show: true, title: 'Agent team', sub: done ? `${fi.P.usedCount} of 9 agents used · ${escalated ? '1 human handoff' : '0 humans in the loop'}` : fi.cur >= 0 ? `Working now: ${FLOW[fi.cur].name}` : 'Getting ready…', badge: `${fi.P.usedCount}/9` },
    { k: 'decision', show: shown('insight') || shown('eval'), title: 'What the AI knew and chose', sub: ev && shown('eval') ? (ev.options ? `Chose option ${ev.selected}: ${(ev.options.find((o) => o.id === ev.selected) || {}).label || ''}` : `Intent ${ev.route?.intent}`) : 'Recalling this merchant’s history…', badge: ev && ev.options && shown('eval') ? `Option ${ev.selected}` : '' },
    { k: 'result', show: shown('reply'), title: 'Result', sub: `${(totalMs / 1000).toFixed(1)}s · the ledger already changed`, badge: resBadge, tone: get('reply')?.tone === 'bad' ? 'bad' : awaiting || escalated ? 'esc' : 'good' },
    { k: 'log', show: !!(done && run.live && run.events?.length), title: 'Compliance log', sub: 'Real agent-to-agent and DPDP events', badge: run?.events?.length ? String(run.events.length) : '' },
    { k: 'tech', show: !!(run && shown('dispatch') && disp), title: 'Technical details', sub: 'A2A request and response (JSON)', badge: '' },
  ].filter((s) => s.show) : []
  if (done) sections.sort((a, b) => (a.k === 'result' ? -1 : b.k === 'result' ? 1 : 0))

  const body = {
    agents: <AgentFlow run={run} reveal={reveal} done={done} escalated={escalated} totalMs={totalMs} />,
    decision: (
      <>
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
      </>
    ),
    result: shown('reply') && (
      <div className={`tcard in result ${get('reply').tone === 'bad' ? 'bad' : awaiting || escalated ? 'esc' : 'good'}`}>
        <div className="res-h">
          <span className="res-b">{resBadge}</span>
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
    ),
    log: done && run.live && run.events?.length > 0 && (
      <div className="tcard in">
        {run.events.map((e) => (
          <div key={e.seq} className="evt"><code>{e.type}</code><span className="muted xs">{e.actor}</span><div className="sm">{e.summary}</div></div>
        ))}
      </div>
    ),
    tech: disp && (
      <div className="json">
        <div><span className="muted xs">REQUEST · :8003 → :8002 /a2a/dispatch</span><pre>{JSON.stringify(disp.request, null, 1)}</pre></div>
        <div><span className="muted xs">RESPONSE</span><pre>{JSON.stringify(disp.response, null, 1)}</pre></div>
      </div>
    ),
  }

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
          <div className={`caption ${done ? 'ok' : ''}`}>{done ? 'Done — open any section below for details' : `${CAPTION[cur?.key] || 'Starting…'}…`}</div>
        </>
      )}

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

      {sections.map((s) => (
        <Section key={s.k} title={s.title} sub={s.sub} badge={s.badge} tone={s.tone} open={!!openSet[s.k]} onToggle={() => toggle(s.k)}>
          {body[s.k]}
        </Section>
      ))}
    </div>
  )
}
