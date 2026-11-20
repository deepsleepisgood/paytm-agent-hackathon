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
      chip: hi ? 'Aaj ka zaroori kaam' : 'Needs your attention today', photo: false,
      title: hi ? `Bank mein ${inr(st.variance)} kam aaye` : `${inr(st.variance)} less than expected in your bank`,
      text: hi ? `Sale ${inr(st.gross)} ki thi, par bank mein ${inr(st.net)} aaye. Dekhiye ye ${inr(st.variance)} kahan kate.` : `You sold ${inr(st.gross)} but ${inr(st.net)} reached your bank. See exactly where the ${inr(st.variance)} went.`,
      cta: hi ? 'Kahan kata, dekhiye' : 'See where it went',
      stats: [{ k: hi ? 'Kata' : 'Cut', v: inr(st.variance) }, { k: hi ? 'Bank mein' : 'In your bank', v: inr(st.net) }, { k: hi ? 'Sale ka' : 'Of your sales', v: ((st.variance / st.gross) * 100).toFixed(1) + '%' }],
      done: L.itc > 0,
      sorted: hi ? `Samjha diya: ${inr(st.variance)} fees, GST, refund, rent aur ek dispute hold mein gaye` : `Explained: ${inr(st.variance)} went to fees, GST, a refund, rent and a held dispute`,
    })
  }
  const cb = m.d.chargeback
  if (cb) {
    items.push({
      id: 'cb', level: 'urgent', run: 'cb',
      chip: hi ? 'Aaj ka zaroori kaam' : 'Needs your attention today', photo: true,
      title: hi ? `${cb.order} ka ${inr(cb.amount)} ruka hua hai` : `${inr(cb.amount)} is on hold for ${cb.order}`,
      text: hi ? 'Customer ne dispute kiya hai. 48 ghante mein delivery ka proof bhejiye, paisa chhoot jayega.' : 'A customer raised a dispute. Send proof of delivery within 48 hours to get the money released.',
      cta: hi ? 'Proof ki photo bhejiye' : 'Send proof photo',
      stats: [{ k: hi ? 'Amount' : 'Amount', v: inr(cb.amount) }, { k: hi ? 'Time bacha' : 'Time left', v: '48h' }, { k: hi ? 'Order' : 'Order', v: cb.order }],
      done: L.chargeback?.status === 'RELEASED',
      sorted: hi ? `${inr(cb.amount)} chhoot gaye (${cb.order}). Proof maan liya gaya` : `${inr(cb.amount)} released for ${cb.order}. Proof accepted`,
    })
  }
  if (f.cash) {
    const c = f.cash
    items.push({
      id: 'cash', level: 'soon', run: 'shield_edi',
      chip: hi ? 'Kal tak' : 'Due tomorrow',
      title: hi ? 'Kal ka payout kam padega' : 'Tomorrow’s payout will fall short',
      text: hi ? `${inr(c.refund.amount)} ka refund (${c.refund.order}) jane par sirf ${inr(c.projected)} bachega, jabki ${SHORT(c.payable.due)} ko ${c.payable.supplier} ko ${inr(c.payable.amount)} dena hai.`
              : `After the ${inr(c.refund.amount)} refund (${c.refund.order}) you keep only ${inr(c.projected)}, but ${inr(c.payable.amount)} is due to ${c.payable.supplier} on ${SHORT(c.payable.due)}.`,
      cta: hi ? 'EDI roken' : 'Pause EDI',
      stats: [{ k: hi ? 'Refund' : 'Refund', v: inr(c.refund.amount) }, { k: hi ? 'Bachega' : 'You keep', v: inr(c.projected) }, { k: hi ? 'Dena hai' : 'Due', v: inr(c.payable.amount) }],
      done: L.loan.status === 'PAUSED',
      sorted: hi ? 'EDI 2 din ke liye ruk gayi. Kal ka payout surakshit hai' : 'EDI paused for 2 days. Tomorrow’s payout is covered',
    })
  }
  if (f.edi) {
    items.push({
      id: 'edi', level: 'soon', run: 'edi',
      chip: hi ? `${SHORT(f.edi.date)} ko fail` : `Bounced ${SHORT(f.edi.date)}`,
      title: hi ? `${inr(f.edi.amount)} ki EDI fail hui` : `Your ${inr(f.edi.amount)} loan EDI bounced`,
      text: hi ? 'Account mein paise kam the (market band rehne se sale giri). Ye default nahi hai — UPI link se bhariye, penalty nahi lagegi.'
              : 'The balance was short (sales dipped during the market closure). This is not a default — pay by UPI link with no penalty.',
      cta: hi ? 'Theek karein' : 'Fix it',
      stats: [{ k: hi ? 'Amount' : 'Amount', v: inr(f.edi.amount) }, { k: hi ? 'Wajah' : 'Reason', v: hi ? 'Kam balance' : 'Low balance' }, { k: hi ? 'Penalty' : 'Penalty', v: hi ? 'Maaf' : 'Waived' }],
      done: ['LINK_SENT', 'PAUSED', 'QUOTE'].includes(L.loan.status),
      sorted: hi ? 'Loan EDI theek ho gayi. Penalty nahi lagegi' : 'Loan EDI sorted. You will not be charged a penalty',
    })
  }
  if (f.soundbox && f.soundbox.battery < 50) {
    items.push({
      id: 'sb', level: 'info', run: 'soundbox',
      chip: hi ? `Battery ${f.soundbox.battery}%` : `Battery ${f.soundbox.battery}%`,
      title: hi ? `Soundbox ki battery kamzor hai` : 'Your Soundbox battery is weak',
      text: hi ? `Pichhle 4 din mein ${f.soundbox.missed} baar payment ki awaaz nahi aayi. Ticket banakar badalwa dein?` : `Payment announcements failed ${f.soundbox.missed} times in the last 4 days. Shall I raise a replacement ticket?`,
      cta: hi ? 'Ticket banayein' : 'Raise ticket',
      stats: [{ k: hi ? 'Battery' : 'Battery', v: f.soundbox.battery + '%' }, { k: hi ? 'Awaaz nahi aayi' : 'Missed', v: String(f.soundbox.missed) }, { k: hi ? 'Kiraya' : 'Rent', v: '₹149/mo' }],
      done: L.tickets.some((t) => /soundbox/i.test(t.reason || '')) || L.soundbox.status === 'PICKUP',
      sorted: hi ? 'Soundbox ka ticket bana diya. Hum theek karenge' : 'Soundbox ticket raised. We will fix it',
    })
  }
  return items
}
