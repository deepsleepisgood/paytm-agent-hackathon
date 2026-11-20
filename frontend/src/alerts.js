// What needs the merchant's attention today, built from their own data, and whether the ledger shows it as handled.
import { inr } from './data.js'

const SHORT = (iso) => new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

export function buildAlerts(m, L, lang = 'hi') {
  const hi = lang === 'hi'
  const f = m.facts || {}
  const items = []
  const st = m.d.settlement
  if (st && st.variance > 0) {
    items.push({
      id: 'settle', level: 'urgent', run: 'settle',
      chip: hi ? 'आज का ज़रूरी काम' : 'Needs your attention today', photo: false,
      title: hi ? `बैंक में ${inr(st.variance)} कम आए` : `${inr(st.variance)} less than expected in your bank`,
      text: hi ? `बिक्री ${inr(st.gross)} थी, पर बैंक में ${inr(st.net)} आए। देखिए ये ${inr(st.variance)} कहाँ कटे।` : `You sold ${inr(st.gross)} but ${inr(st.net)} reached your bank. See exactly where the ${inr(st.variance)} went.`,
      cta: hi ? 'कटौती देखें' : 'See where it went',
      stats: [{ k: hi ? 'कटा' : 'Cut', v: inr(st.variance) }, { k: hi ? 'बैंक में' : 'In your bank', v: inr(st.net) }, { k: hi ? 'बिक्री का' : 'Of your sales', v: ((st.variance / st.gross) * 100).toFixed(1) + '%' }],
      done: L.itc > 0,
      sorted: hi ? null : `Explained: ${inr(st.variance)} went to fees, GST, a refund, rent and a held dispute`,
    })
  }
  const cb = m.d.chargeback
  if (cb) {
    items.push({
      id: 'cb', level: 'urgent', run: 'cb',
      chip: hi ? 'आज का ज़रूरी काम' : 'Needs your attention today', photo: true,
      title: hi ? `${cb.order} का ${inr(cb.amount)} रुका हुआ है` : `${inr(cb.amount)} is on hold for ${cb.order}`,
      text: hi ? 'ग्राहक ने विवाद किया है। 48 घंटे में डिलीवरी का सबूत भेजिए, तो पैसा छूट जाएगा।' : 'A customer raised a dispute. Send proof of delivery within 48 hours to get the money released.',
      cta: hi ? 'सबूत की फ़ोटो भेजें' : 'Send proof photo',
      stats: [{ k: hi ? 'रकम' : 'Amount', v: inr(cb.amount) }, { k: hi ? 'समय बाकी' : 'Time left', v: '48h' }, { k: hi ? 'ऑर्डर' : 'Order', v: cb.order }],
      done: L.chargeback?.status === 'RELEASED',
      sorted: hi ? null : `${inr(cb.amount)} released for ${cb.order}. Proof accepted`,
    })
  }
  if (f.cash) {
    const c = f.cash
    items.push({
      id: 'cash', level: 'soon', run: 'shield_edi',
      chip: hi ? 'कल तक' : 'Due tomorrow',
      title: hi ? 'कल का पेआउट कम पड़ेगा' : 'Tomorrow’s payout will fall short',
      text: hi ? `${inr(c.refund.amount)} का रिफंड (${c.refund.order}) जाने पर सिर्फ़ ${inr(c.projected)} बचेगा, जबकि ${SHORT(c.payable.due)} को ${c.payable.supplier} को ${inr(c.payable.amount)} देना है।`
              : `After the ${inr(c.refund.amount)} refund (${c.refund.order}) you keep only ${inr(c.projected)}, but ${inr(c.payable.amount)} is due to ${c.payable.supplier} on ${SHORT(c.payable.due)}.`,
      cta: hi ? 'EDI रोकें' : 'Pause EDI',
      stats: [{ k: hi ? 'रिफंड' : 'Refund', v: inr(c.refund.amount) }, { k: hi ? 'बचेगा' : 'You keep', v: inr(c.projected) }, { k: hi ? 'देना है' : 'Due', v: inr(c.payable.amount) }],
      done: L.loan.status === 'PAUSED',
      sorted: hi ? null : 'EDI paused for 2 days. Tomorrow’s payout is covered',
    })
  }
  if (f.edi) {
    items.push({
      id: 'edi', level: 'soon', run: 'edi',
      chip: hi ? `${SHORT(f.edi.date)} को फेल` : `Bounced ${SHORT(f.edi.date)}`,
      title: hi ? `${inr(f.edi.amount)} की EDI फेल हुई` : `Your ${inr(f.edi.amount)} loan EDI bounced`,
      text: hi ? 'खाते में पैसे कम थे (बाज़ार बंद रहने से बिक्री गिरी)। यह डिफ़ॉल्ट नहीं है — UPI लिंक से भरिए, पेनल्टी नहीं लगेगी।'
              : 'The balance was short (sales dipped during the market closure). This is not a default — pay by UPI link with no penalty.',
      cta: hi ? 'ठीक करें' : 'Fix it',
      stats: [{ k: hi ? 'रकम' : 'Amount', v: inr(f.edi.amount) }, { k: hi ? 'वजह' : 'Reason', v: hi ? 'कम बैलेंस' : 'Low balance' }, { k: hi ? 'पेनल्टी' : 'Penalty', v: hi ? 'माफ़' : 'Waived' }],
      done: ['LINK_SENT', 'PAUSED', 'QUOTE'].includes(L.loan.status),
      sorted: hi ? null : 'Loan EDI sorted. You will not be charged a penalty',
    })
  }
  if (f.soundbox && f.soundbox.battery < 50) {
    items.push({
      id: 'sb', level: 'info', run: 'soundbox',
      chip: hi ? `बैटरी ${f.soundbox.battery}%` : `Battery ${f.soundbox.battery}%`,
      title: hi ? `साउंडबॉक्स की बैटरी कमज़ोर है` : 'Your Soundbox battery is weak',
      text: hi ? `पिछले 4 दिनों में ${f.soundbox.missed} बार पेमेंट की आवाज़ नहीं आई। टिकट बनाकर बदलवा दें?` : `Payment announcements failed ${f.soundbox.missed} times in the last 4 days. Shall I raise a replacement ticket?`,
      cta: hi ? 'टिकट बनाएँ' : 'Raise ticket',
      stats: [{ k: hi ? 'बैटरी' : 'Battery', v: f.soundbox.battery + '%' }, { k: hi ? 'आवाज़ नहीं आई' : 'Missed', v: String(f.soundbox.missed) }, { k: hi ? 'किराया' : 'Rent', v: '₹149/mo' }],
      done: L.tickets.some((t) => /soundbox/i.test(t.reason || '')) || L.soundbox.status === 'PICKUP',
      sorted: hi ? null : 'Soundbox ticket raised. We will fix it',
    })
  }
  return items
}
