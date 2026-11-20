// Hindi + English UI strings for the voice Assistant. Merchant picks a language once; the choice is remembered.
export const LANGS = { hi: 'Hinglish', en: 'EN' }
const KEY = 'paytm-ai-lang'
// The deployed demo is English-only. Set to false to bring back the Hindi / English toggle.
export const ENGLISH_ONLY = true
export const loadLang = () => { if (ENGLISH_ONLY) return 'en'; try { const v = localStorage.getItem(KEY); return v in LANGS ? v : 'hi' } catch { return 'hi' } }
export const saveLang = (l) => { try { localStorage.setItem(KEY, l) } catch { /* ignore */ } }

export const STR = {
  hi: {
    idle: 'Mic dabakar boliye', listen: 'Sun raha hoon…', think: 'Soch raha hoon…', speak: 'Bata raha hoon', more: 'Aur kuch poochna hai?',
    ph: 'Boliye…', intro: 'Hindi ya English mein poochiye',
    unclear: 'Awaaz samajh nahi aayi. Neeche se koi sawaal chun lijiye.', silent: 'Kuch sunai nahi diya. Mic dabakar phir se boliye.', nomic: 'Yahan mic nahi chal raha. Neeche se koi sawaal chun lijiye.',
    needLive: 'Awaaz ke liye Live services chalaiye, ya neeche se koi sawaal chuniye.',
    yesSay: 'ya boliye “haan”', nudgeLabel: 'Aaj ka zaroori kaam', nudgeCta: 'Proof ki photo bhejiye', nudgeDemo: 'Demo dekhiye',
    up: 'Photo bhejiye', ask: 'Bolkar aur poochiye', stop: 'Bol chuka, bhejiye', menu: 'Saari madad', khata: 'Khata', askVoice: 'Bolkar poochiye', typePh: 'Ya yahan likhiye…', send: 'Bhejiye', cUnclear: 'Phir se poochiye', cBooks: 'Aapke khate se',
    asH: 'Kya bhejna hai?', asPodT: 'Delivery ka proof', asPodS: 'Customer ko saman mil gaya — receipt ya photo', asShotT: 'UPI payment ka screenshot', asShotS: 'Customer ne payment dikhaya — asli hai ya nahi, check karein',
    asNote: 'Camera se photo lijiye ya gallery se chuniye', cancel: 'Cancel', mute: 'Awaaz band karein', unmute: 'Awaaz chalu karein',
    p_settle: 'Paisa kahan kata?', p_utr: 'UTR check karo', p_cb: 'Delivery proof bhejo', p_hold: 'Settlement hold', p_edi: 'Loan EDI fail', p_dup: 'Do baar paisa kata', p_growth: 'Business kaise badhayein',
    nTitleCb: (o, a) => `${o} ka ₹${a} ruka hua hai`, nTextCb: 'Delivery ka proof bhejiye, paisa 48 ghante mein chhoot jayega.', nTitleSt: 'Aaj ka hisaab dekhiye', nTextSt: 'Settlement mein kitna kata, ek button mein jaaniye.',
    cHold: 'Ho gaya', cWait: 'Aapki manzoori chahiye', cTeam: 'Team ko bheja', cFake: 'Account mein nahi mila', cPend: 'Pending',
    attn: 'ध्यान दीजिए', attnSub: 'क्या हुआ और अब क्या करना है', clear: 'सब ठीक है', clearSub: 'अभी कोई ज़रूरी काम बाकी नहीं है', handled: 'हो गया', showAll: 'सभी देखें', showLess: 'कम दिखाएँ',
  },
  en: {
    idle: 'Tap the mic and speak', listen: 'Listening…', think: 'Thinking…', speak: 'Speaking', more: 'Anything else?',
    ph: 'Go ahead…', intro: 'Ask in Hindi or English',
    unclear: 'I could not understand that. Pick a question below.', silent: 'I did not hear anything. Tap the mic and try again.', nomic: 'The mic is not available here. Pick a question below.',
    needLive: 'Turn on Live services for voice, or pick a question below.',
    yesSay: 'or say “yes”', nudgeLabel: 'Needs your attention today', nudgeCta: 'Send proof photo', nudgeDemo: 'See demo',
    up: 'Send a photo', ask: 'Ask another question', stop: 'Done, send it', menu: 'All help', khata: 'Khata', askVoice: 'Ask by voice', typePh: 'Or type here…', send: 'Send', cUnclear: 'Please rephrase', cBooks: 'From your books',
    asH: 'What are you sending?', asPodT: 'Proof of delivery', asPodS: 'The customer got the item — receipt or photo', asShotT: 'UPI payment screenshot', asShotS: 'Customer showed a payment — check if it is real',
    asNote: 'Take a photo with the camera or choose from gallery', cancel: 'Cancel', mute: 'Mute voice replies', unmute: 'Unmute voice replies',
    p_settle: 'Why was money cut?', p_utr: 'Check a UTR', p_cb: 'Send delivery proof', p_hold: 'Settlement hold', p_edi: 'Loan EDI failed', p_dup: 'Charged twice', p_growth: 'Grow my business',
    nTitleCb: (o, a) => `₹${a} is on hold for ${o}`, nTextCb: 'Send the delivery proof and the money is released within 48 hours.', nTitleSt: 'See today’s settlement', nTextSt: 'Find out what was deducted, in one tap.',
    attn: 'Needs your attention', attnSub: 'What happened and what to do now', clear: 'All clear', clearSub: 'Nothing urgent needs you right now', handled: 'Handled', showAll: 'View all', showLess: 'Show less',
    cHold: 'Done', cWait: 'Needs your OK', cTeam: 'Sent to team', cFake: 'Looks fake', cPend: 'Pending',
  },
}
export const t = (lang, k, ...a) => { const v = STR[lang][k]; return typeof v === 'function' ? v(...a) : v }

export const FACT = {
  hi: {
    gross: 'Kul sale', net_bank_credit: 'Bank mein aaya', variance: 'Kul katauti', utr: 'UTR', utr_number: 'UTR', amount: 'Amount', amount_inr: 'Amount', payer_app: 'Payment app', order_id: 'Order',
    outstanding: 'Baaki loan', payable: 'Bharna hai', foreclosure_charge: 'Closure charge', noc_eta_days: 'NOC (din)', pickup_ticket: 'Ticket', ticket: 'Ticket', release_eta: 'Paisa kab milega',
    edi_saved_inr: 'Bachat', order_amount_inr: 'Order amount', projected_net_payout: 'Kal ka payout', duplicates_found: 'Duplicate', pickup_within_hours: 'Pickup (ghante)', eta_hours: 'Samay (ghante)', current_account: 'Bank account', lender: 'Lender', settlement_date: 'Tareekh',
  },
  en: {
    gross: 'Total sales', net_bank_credit: 'Credited to bank', variance: 'Total deductions', utr: 'UTR', utr_number: 'UTR', amount: 'Amount', amount_inr: 'Amount', payer_app: 'Payment app', order_id: 'Order',
    outstanding: 'Loan balance', payable: 'To pay', foreclosure_charge: 'Closure charge', noc_eta_days: 'NOC (days)', pickup_ticket: 'Ticket', ticket: 'Ticket', release_eta: 'Money released',
    edi_saved_inr: 'You save', order_amount_inr: 'Order amount', projected_net_payout: 'Tomorrow’s payout', duplicates_found: 'Duplicates', pickup_within_hours: 'Pickup (hours)', eta_hours: 'Time (hours)', current_account: 'Bank account', lender: 'Lender', settlement_date: 'Date',
  },
}
export const STATUS = {
  hi: { PENDING: 'Pending', SUCCESS: 'Safal', RELEASED: 'Chhoot gaya', RESOLVED: 'Hal ho gaya', RECONCILED: 'Hisaab mil gaya', PROCESSED: 'Ho gaya', NOT_FOUND_SUSPECTED_FAKE: 'Account mein nahi mila', ESCALATED: 'Team ko bheja', RETURN_INITIATED: 'Pickup tay', FORECLOSURE_QUOTE_READY: 'Quote taiyaar', KYC_UPDATE_LINK_SENT: 'Link bheja', NO_BANK_HOLD: 'Koi hold nahi', ACTION_REQUIRED: 'Aapki manzoori chahiye', ALERT_RAISED: 'Aapki manzoori chahiye', EDI_PAUSED: 'EDI ruka', REFUND_INITIATED: 'Refund shuru', ALL_CLEAR: 'Sab theek', DUPLICATE_FOUND: 'Do baar pay' },
  en: { PENDING: 'Pending', SUCCESS: 'Successful', RELEASED: 'Released', RESOLVED: 'Resolved', RECONCILED: 'Explained', PROCESSED: 'Processed', NOT_FOUND_SUSPECTED_FAKE: 'Looks fake', ESCALATED: 'Sent to team', RETURN_INITIATED: 'Pickup scheduled', FORECLOSURE_QUOTE_READY: 'Quote ready', KYC_UPDATE_LINK_SENT: 'Link sent', NO_BANK_HOLD: 'No hold', ACTION_REQUIRED: 'Needs your OK', ALERT_RAISED: 'Needs your OK', EDI_PAUSED: 'EDI paused', REFUND_INITIATED: 'Refund started', ALL_CLEAR: 'All clear', DUPLICATE_FOUND: 'Paid twice' },
}

