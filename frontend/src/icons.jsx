import React from 'react'

const P = ({ d, children, size = 24, stroke = 'currentColor', fill = 'none', sw = 1.8 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={stroke} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">
    {d ? <path d={d} /> : children}
  </svg>
)

export const I = {
  Home: (p) => <P {...p}><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></P>,
  History: (p) => <P {...p}><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /><path d="M12 8v4l3 2" /></P>,
  Speaker: (p) => <P {...p}><rect x="5" y="3" width="14" height="18" rx="3" /><circle cx="12" cy="14" r="3.5" /><circle cx="12" cy="7" r=".8" /></P>,
  Loan: (p) => <P {...p}><rect x="3" y="6" width="18" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /><path d="M6 9v.01M18 15v.01" /></P>,
  User: (p) => <P {...p}><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-6 8-6s8 2 8 6" /></P>,
  Bell: (p) => <P {...p}><path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z" /><path d="M10 21h4" /></P>,
  Help: (p) => <P {...p}><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7" /><path d="M12 17v.01" /></P>,
  QR: (p) => <P {...p}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><path d="M14 14h3v3h-3zM20 14v.01M14 20h3M20 17v4" /></P>,
  Settle: (p) => <P {...p}><path d="M3 10l9-6 9 6" /><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18" /></P>,
  Refund: (p) => <P {...p}><path d="M9 14L4 9l5-5" /><path d="M4 9h10a6 6 0 0 1 0 12h-3" /></P>,
  Report: (p) => <P {...p}><path d="M6 3h9l4 4v14H6z" /><path d="M9 13h7M9 17h7M9 9h3" /></P>,
  Offer: (p) => <P {...p}><path d="M20 12l-8 8-9-9V3h8z" /><circle cx="7.5" cy="7.5" r="1.2" /></P>,
  Shield: (p) => <P {...p}><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" /></P>,
  Chev: (p) => <P {...p} sw={2}><path d="M9 6l6 6-6 6" /></P>,
  Back: (p) => <P {...p} sw={2}><path d="M15 6l-6 6 6 6" /></P>,
  Eye: (p) => <P {...p}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></P>,
  Scan: (p) => <P {...p}><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M4 12h16" /></P>,
  Down: (p) => <P {...p}><path d="M12 4v12M6 12l6 6 6-6" /></P>,
  Check: (p) => <P {...p} sw={2.4}><path d="M5 12l5 5 9-10" /></P>,
  Alert: (p) => <P {...p}><path d="M12 3l10 18H2z" /><path d="M12 10v5M12 18v.01" /></P>,
  Spark: (p) => <P {...p}><path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" /></P>,
  Bank: (p) => <P {...p}><path d="M3 10l9-6 9 6H3z" /><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 20h18" /></P>,
  Plus: (p) => <P {...p} sw={2}><path d="M12 5v14M5 12h14" /></P>,
}

// Paytm for Business wordmark. If you drop the official file at frontend/public/paytm-business-logo.png
// it is used automatically; otherwise this CSS/text wordmark is shown.
export function PaytmLogo({ size = 30 }) {
  const [ok, setOk] = React.useState(true)
  if (ok)
    return <img src="/paytm-business-logo.png" alt="Paytm for Business" height={size * 2.6} onError={() => setOk(false)} style={{ display: 'block', margin: '-12px 0 -12px -14px' }} />
  return (
    <span className="logo" style={{ fontSize: size }} aria-label="Paytm for Business">
      <span className="lg-top"><b className="pay">pay</b><b className="tm">tm</b></span>
      <span className="lg-for"><i />for<i /></span>
      <span className="lg-biz">Business</span>
    </span>
  )
}

// Option B "Neural node" (alternate, not used right now): navy rounded square, white core node linked to three cyan agent nodes.
// Nodes pulse while the AI is working. Active mark is AIMark below (option C aura ring).
export const AIMarkNeural = ({ size = 48 }) => (
  <svg width={size} height={size} viewBox="0 0 120 120" role="img" aria-label="AI assistant" style={{ display: 'block' }}>
    <rect x="12" y="12" width="96" height="96" rx="30" fill="#002E6E" />
    <g stroke="#FFFFFF" strokeWidth="3" strokeLinecap="round">
      <line x1="60" y1="60" x2="36" y2="40" /><line x1="60" y1="60" x2="84" y2="40" /><line x1="60" y1="60" x2="60" y2="88" />
    </g>
    <circle cx="60" cy="60" r="9" fill="#FFFFFF" />
    <circle className="nd nd1" cx="36" cy="40" r="7" fill="#00BAF2" />
    <circle className="nd nd2" cx="84" cy="40" r="7" fill="#00BAF2" />
    <circle className="nd nd3" cx="60" cy="88" r="7" fill="#00BAF2" />
  </svg>
)

export const AIMark = ({ size = 48 }) => (
  <svg width={size} height={size} viewBox="0 0 120 120" role="img" aria-label="AI assistant" style={{ display: 'block' }}>
    <circle className="aura-ring" cx="60" cy="60" r="54" fill="none" stroke="#00BAF2" strokeWidth="6" strokeDasharray="46 9" strokeLinecap="round" />
    <circle cx="60" cy="60" r="41" fill="#002E6E" />
    <path d="M60 38 Q63.3 56.7 82 60 Q63.3 63.3 60 82 Q56.7 63.3 38 60 Q56.7 56.7 60 38 Z" fill="#FFFFFF" />
  </svg>
)
