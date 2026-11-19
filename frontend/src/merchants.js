// Loads the SME dataset from /dataset/merchants and adapts it to the shape the UI screens use.
import index from '../../dataset/merchants/index.json'

const files = import.meta.glob('../../dataset/merchants/*/*.json', { eager: true })

const NOTES = {
  MDR_FEE: '2% card · 1.1% wallet-on-UPI >₹2k · 0% bank UPI',
  GST_ON_MDR: 'ITC eligible if GST regular',
  CUSTOMER_REFUND: 'Processed',
  SOUNDBOX_RENTAL: 'Monthly device rental',
  CHARGEBACK_HOLD: 'Held · PoD due in 48h',
}

function load(slug) {
  const pick = (n) => files[`../../dataset/merchants/${slug}/${n}.json`]?.default
  const profile = pick('profile')
  const settlement = pick('settlement')
  const loan = pick('loan')
  const orders = pick('orders')
  const insights = pick('insights')
  const transactions = pick('transactions')
  const refunds = orders.orders.filter((o) => o.type === 'REFUND')
  const cb = orders.orders.find((o) => o.type === 'CHARGEBACK') || null
  return {
    slug,
    mid: profile.mid,
    profile,
    insights,
    orders,
    // shape used by the Paytm-clone screens
    d: {
      mid: profile.mid,
      merchant: profile.name,
      settlement: {
        date: settlement.date,
        gross: settlement.gross,
        mix: settlement.gross_mix,
        net: settlement.net_bank_credit,
        variance: settlement.variance,
        deductions: settlement.deductions.map((x) => ({
          key: x.code,
          label: x.label,
          note: x.ref ? `${x.ref} · ${x.status || ''}` : NOTES[x.code] || '',
          amount: x.amount,
        })),
      },
      loan: {
        edi: loan.edi_per_day,
        next: loan.next_deduction,
        balance: loan.balance,
        principal: Math.round(loan.balance / 0.55 / 1000) * 1000,
        offer: loan.offer_up_to,
      },
      chargeback: cb && { txn: cb.txn_id, order: cb.order_id, amount: cb.amount, status: cb.status },
      transactions: [
        ...transactions.map((t) => ({ utr: t.utr, amount: t.amount, app: t.payer_app, status: t.status, time: t.time, name: t.payer })),
        ...refunds.map((r) => ({ utr: 'REF' + r.order_id.replace(/\D/g, ''), amount: r.amount, app: 'Refund', status: 'REFUNDED', time: '02:10 PM', name: 'Order ' + r.order_id })),
      ],
    },
  }
}

export const MERCHANTS = Object.fromEntries(index.merchants.map((m) => [m.slug, load(m.slug)]))
export const MERCHANT_LIST = index.merchants.map((m) => ({ slug: m.slug, name: m.name, type: m.type }))
export const DEFAULT_MERCHANT = index.merchants.find((m) => m.mid === index.default_mid)?.slug || index.merchants[0].slug
