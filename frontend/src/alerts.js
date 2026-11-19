// What needs the merchant's attention today, built from their own data, and whether the ledger shows it as handled.
import { inr } from './data.js'

const SHORT = (iso) => new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

export function buildAlerts(m, L, lang = 'hi') {
  const hi = lang === 'hi'
  const f = m.facts || {}
  const items = []
  const cb = m.d.chargeback
  if (cb) {
    items.push({
      id: 'cb', level: 'urgent', run: 'cb',
      chip: hi ? '48 घंटे बाकी' : '48h left',
      title: hi ? `${cb.order} का ${inr(cb.amount)} रुका हुआ है` : `${inr(cb.amount)} is on hold for ${cb.order}`,
      text: hi ? 'ग्राहक ने विवाद किया है। 48 घंटे में डिलीवरी का सबूत भेजिए, तो पैसा छूट जाएगा।' : 'A customer raised a dispute. Send proof of delivery within 48 hours to get the money released.',
      cta: hi ? 'सबूत भेजें' : 'Send proof',
      done: L.chargeback?.status === 'RELEASED',
    })
  }
  if (f.cash) {
    const c = f.cash
    items.push({
      id: 'cash', level: 'attn', run: 'shield_edi',
      chip: hi ? 'कल तक' : 'By tomorrow',
      title: hi ? 'कल का पेआउट कम पड़ेगा' : 'Tomorrow’s payout will fall short',
      text: hi ? `${inr(c.refund.amount)} का रिफंड (${c.refund.order}) जाने पर सिर्फ़ ${inr(c.projected)} बचेगा, जबकि ${SHORT(c.payable.due)} को ${c.payable.supplier} को ${inr(c.payable.amount)} देना है।`
              : `After the ${inr(c.refund.amount)} refund (${c.refund.order}) you keep only ${inr(c.projected)}, but ${inr(c.payable.amount)} is due to ${c.payable.supplier} on ${SHORT(c.payable.due)}.`,
      cta: hi ? 'EDI रोकें' : 'Pause EDI',
      done: L.loan.status === 'PAUSED',
    })
  }
  if (f.edi) {
    items.push({
      id: 'edi', level: 'attn', run: 'edi',
      chip: SHORT(f.edi.date),
      title: hi ? `${inr(f.edi.amount)} की EDI फेल हुई` : `Your ${inr(f.edi.amount)} loan EDI bounced`,
      text: hi ? 'खाते में पैसे कम थे (बाज़ार बंद रहने से बिक्री गिरी)। यह डिफ़ॉल्ट नहीं है — UPI लिंक से भरिए, पेनल्टी नहीं लगेगी।'
              : 'The balance was short (sales dipped during the market closure). This is not a default — pay by UPI link with no penalty.',
      cta: hi ? 'ठीक करें' : 'Fix it',
      done: ['LINK_SENT', 'PAUSED', 'QUOTE'].includes(L.loan.status),
    })
  }
  if (f.soundbox && f.soundbox.battery < 50) {
    items.push({
      id: 'sb', level: 'info', run: 'soundbox',
      chip: `${f.soundbox.battery}%`,
      title: hi ? `साउंडबॉक्स की बैटरी कमज़ोर है` : 'Your Soundbox battery is weak',
      text: hi ? `पिछले 4 दिनों में ${f.soundbox.missed} बार पेमेंट की आवाज़ नहीं आई। टिकट बनाकर बदलवा दें?` : `Payment announcements failed ${f.soundbox.missed} times in the last 4 days. Shall I raise a replacement ticket?`,
      cta: hi ? 'टिकट बनाएँ' : 'Raise ticket',
      done: L.tickets.some((t) => /soundbox/i.test(t.reason || '')) || L.soundbox.status === 'PICKUP',
    })
  }
  return items
}
