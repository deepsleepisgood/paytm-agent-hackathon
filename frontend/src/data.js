// Unified seed data from contract.md (MID PAYTM_MERCH_8821 — Sharma Electronics).
// Used as the offline fallback when the Paytm agent (8002) is not running.
export const inr = (n) => '₹' + Number(n).toLocaleString('en-IN')

export const SEED = {
  mid: 'PAYTM_MERCH_8821',
  merchant: 'Sharma Electronics',
  settlement: {
    date: '2026-11-18',
    gross: 100000,
    net: 95840,
    variance: 4160,
    deductions: [
      { key: 'mdr', label: 'MDR Fee', note: '2% Credit Card · 1.1% Wallet-on-UPI >₹2k · 0% Bank UPI', amount: 1450 },
      { key: 'gst', label: 'GST on MDR (18%)', note: 'ITC eligible', amount: 261 },
      { key: 'refund', label: 'Customer Refund', note: 'ORDER #4412 · Processed', amount: 1500 },
      { key: 'soundbox', label: 'Soundbox Rental', note: 'Monthly device rental', amount: 149 },
      { key: 'chargeback', label: 'Chargeback Hold', note: 'TXNID #9981 · Held · PoD due in 48h', amount: 800 },
    ],
  },
  loan: { edi: 500, next: 'Tomorrow’s settlement', balance: 42000 },
  chargeback: { txn: '#9981', order: '#9981', amount: 800, status: 'HELD', due: '48h' },
  transactions: [
    { utr: '632184920111', amount: 1250, app: 'GPay', status: 'SUCCESS', time: '10:42 AM', name: 'Rohit Verma' },
    { utr: '632184920999', amount: 2400, app: 'PhonePe', status: 'PENDING', time: '11:15 AM', name: 'Anita Singh' },
    { utr: '632184920304', amount: 780, app: 'Paytm', status: 'SUCCESS', time: '12:03 PM', name: 'Karan Mehta' },
    { utr: '632184920455', amount: 3200, app: 'Paytm', status: 'SUCCESS', time: '01:27 PM', name: 'Pooja Nair' },
    { utr: '632184920512', amount: 1500, app: 'BHIM', status: 'REFUNDED', time: '02:10 PM', name: 'Order #4412' },
  ],
  stats: { ticketsDeflected: 0, fraudBlocked: 0 },
}
