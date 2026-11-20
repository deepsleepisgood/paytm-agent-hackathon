import React from 'react'

// Buddy brand: a glassy two-tone B with a green "hand-over" dot. One component, five calm states.
//   state: 'static' | 'idle' | 'listening' | 'working' | 'done' | 'need'
//   variant: 'color' (on light) | 'white' (on dark)
const B_STEM = 'M36 18H44V102H36A8 8 0 0 1 28 94V26A8 8 0 0 1 36 18Z'
const B_UP = 'M44 18H66A19 19 0 0 1 66 56H44Z'
const B_LO = 'M44 62H69A20 20 0 0 1 69 102H44Z'

export function BuddyMark({ size = 48, state = 'static', variant = 'color', glow = false, className = '', title = 'Buddy' }) {
  const id = React.useId().replace(/:/g, '')
  const white = variant === 'white'
  return (
    <svg className={`bd bd-${state} ${glow ? 'bd-glow' : ''} ${className}`} width={size} height={size} viewBox="0 0 120 120" role="img" aria-label={title} style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={`u${id}`} x1="0.1" y1="0" x2="0.9" y2="1">
          {white ? <><stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#d9e8ff" /></> : <><stop offset="0" stopColor="#3a5fd0" /><stop offset="1" stopColor="#12296f" /></>}
        </linearGradient>
        <linearGradient id={`l${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#d4ebff" /><stop offset=".55" stopColor="#7cbcf8" /><stop offset="1" stopColor="#4a95ee" />
        </linearGradient>
        <linearGradient id={`s${id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fff" stopOpacity=".5" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></linearGradient>
        <linearGradient id={`h${id}`} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#fff" stopOpacity=".45" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></linearGradient>
        <radialGradient id={`d${id}`} cx=".35" cy=".3" r=".8"><stop offset="0" stopColor="#c6ffe0" /><stop offset=".5" stopColor="#34d399" /><stop offset="1" stopColor="#12935f" /></radialGradient>
        <clipPath id={`cu${id}`}><path d={B_UP} /></clipPath>
        <clipPath id={`cl${id}`}><path d={B_LO} /></clipPath>
        <clipPath id={`cs${id}`}><path d={B_STEM} /></clipPath>
      </defs>
      <path d={B_STEM} fill={`url(#l${id})`} />
      <path d={B_UP} fill={`url(#u${id})`} />
      <path d={B_LO} fill={`url(#l${id})`} />
      {/* reflections: a soft sheen across the top of each bowl and a rim light down the stem */}
      <rect x="44" y="18" width="48" height="15" fill={`url(#s${id})`} clipPath={`url(#cu${id})`} opacity={white ? 0.25 : 0.7} />
      <rect x="44" y="62" width="48" height="13" fill={`url(#s${id})`} clipPath={`url(#cl${id})`} opacity=".8" />
      <rect x="28" y="18" width="7" height="84" fill={`url(#h${id})`} clipPath={`url(#cs${id})`} />
      <g fill="none" stroke="#fff" strokeOpacity=".28" strokeWidth="1">
        <path d={B_UP} clipPath={`url(#cu${id})`} /><path d={B_LO} clipPath={`url(#cl${id})`} />
      </g>
      <g className="bd-dotg">
        <circle className="bd-rip" cx="99" cy="59" r="7" />
        <circle className="bd-dot" cx="99" cy="59" r="7" fill={`url(#d${id})`} />
        <circle cx="96.8" cy="56.6" r="2" fill="#fff" fillOpacity=".7" />
        <path className="bd-chk" d="M93 59l4.5 4.5 8-9" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  )
}

// Spaced capitals drawn from strokes (no font needed), blue to ice gradient, with a small sparkle.
const CAP = 56
const LETTERS = {
  B: { w: 38, d: (x) => `M${x} 0V${CAP}M${x} 0H${x + 20}A14 14 0 0 1 ${x + 20} 28H${x}M${x} 28H${x + 24}A14 14 0 0 1 ${x + 24} ${CAP}H${x}` },
  U: { w: 36, d: (x) => `M${x} 0V36A18 18 0 0 0 ${x + 36} 36V0` },
  D: { w: 44, d: (x) => `M${x} 0H${x + 16}A28 28 0 0 1 ${x + 16} ${CAP}H${x}V0` },
  Y: { w: 36, d: (x) => `M${x} 0L${x + 18} 30L${x + 36} 0M${x + 18} 30V${CAP}` },
}
function layout(text, gap = 24) {
  let x = 6, d = ''
  for (const ch of text) { const L = LETTERS[ch]; d += L.d(x); x += L.w + gap }
  return { d, end: x - gap + 6 }
}

export function BuddyWordmark({ height = 24, on = 'dark', sparkle = true, text = 'BUDDY', className = '' }) {
  const id = React.useId().replace(/:/g, '')
  const { d, end } = layout(text)
  const W = end + (sparkle ? 46 : 6)
  const [a, b] = on === 'dark' ? ['#2f6fe8', '#d6e8ff'] : ['#1740a8', '#3b82e8']
  return (
    <svg className={className} width={(height * W) / 68} height={height} viewBox={`-6 -6 ${W} 68`} role="img" aria-label={text} style={{ display: 'block', overflow: 'visible' }}>
      <defs><linearGradient id={`w${id}`} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2={end} y2="0"><stop offset="0" stopColor={a} /><stop offset="1" stopColor={b} /></linearGradient></defs>
      <path d={d} fill="none" stroke={`url(#w${id})`} strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" />
      {sparkle && <path transform={`translate(${end + 24} 28)`} d="M0 -15C2 -5 5 -2 15 0C5 2 2 5 0 15C-2 5 -5 2 -15 0C-5 -2 -2 -5 0 -15Z" fill={on === 'dark' ? '#8592a6' : '#a3b0c4'} />}
    </svg>
  )
}

export function BuddyLockup({ size = 40, on = 'light', state = 'static', sparkle = true }) {
  return (
    <span className="bd-lockup" style={{ display: 'inline-flex', alignItems: 'center', gap: Math.round(size * 0.32) }}>
      <BuddyMark size={size} state={state} variant={on === 'dark' ? 'white' : 'color'} />
      <BuddyWordmark height={Math.round(size * 0.46)} on={on === 'dark' ? 'dark' : 'light'} sparkle={sparkle} />
    </span>
  )
}

// The app icon (dark glass squircle, white B, glowing dot) as a component: used for the main tab button.
export function BuddyIcon({ size = 48, state = 'static', rx = 27, className = '' }) {
  const id = React.useId().replace(/:/g, '')
  return (
    <svg className={`bd bd-${state} ${className}`} width={size} height={size} viewBox="0 0 120 120" role="img" aria-label="Buddy" style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#5a95e4" /><stop offset=".45" stopColor="#25469a" /><stop offset="1" stopColor="#101f58" /></linearGradient>
        <linearGradient id={`r${id}`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#fff" stopOpacity=".55" /><stop offset=".5" stopColor="#fff" stopOpacity=".08" /><stop offset="1" stopColor="#fff" stopOpacity=".2" /></linearGradient>
        <linearGradient id={`h${id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fff" stopOpacity=".22" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></linearGradient>
        <linearGradient id={`w${id}`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#d7e6fb" /></linearGradient>
        <linearGradient id={`b${id}`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#cfe8ff" /><stop offset="1" stopColor="#5fabf6" /></linearGradient>
        <radialGradient id={`d${id}`} cx=".35" cy=".3" r=".8"><stop offset="0" stopColor="#b8ffc9" /><stop offset=".55" stopColor="#3de06f" /><stop offset="1" stopColor="#1fb454" /></radialGradient>
        <clipPath id={`c${id}`}><rect width="120" height="120" rx={rx} /></clipPath>
      </defs>
      <rect width="120" height="120" rx={rx} fill={`url(#g${id})`} />
      <g clipPath={`url(#c${id})`}><rect width="120" height="48" fill={`url(#h${id})`} /><path d="M64 0H120V70Z" fill="#fff" fillOpacity=".12" /></g>
      <rect x=".7" y=".7" width="118.6" height="118.6" rx={rx - 0.7} fill="none" stroke={`url(#r${id})`} strokeWidth="1.4" />
      <g transform="translate(60 60) scale(.88) translate(-65 -60)">
        <path d={B_STEM} fill={`url(#w${id})`} /><path d={B_UP} fill={`url(#w${id})`} /><path d={B_LO} fill={`url(#b${id})`} />
        <g className="bd-dotg">
          <circle className="bd-rip" cx="99" cy="59" r="7" />
          <circle className="bd-dot" cx="99" cy="59" r="7" fill={`url(#d${id})`} />
          <circle cx="96.8" cy="56.6" r="2" fill="#fff" fillOpacity=".65" />
          <path className="bd-chk" d="M93 59l4.5 4.5 8-9" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      </g>
    </svg>
  )
}
