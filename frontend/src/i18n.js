// Hindi + English UI strings for the voice Assistant. Merchant picks a language once; the choice is remembered.
export const LANGS = { hi: 'हि', en: 'EN' }
const KEY = 'paytm-ai-lang'
// The deployed demo is English-only. Set to false to bring back the Hindi / English toggle.
export const ENGLISH_ONLY = true
export const loadLang = () => { if (ENGLISH_ONLY) return 'en'; try { const v = localStorage.getItem(KEY); return v in LANGS ? v : 'hi' } catch { return 'hi' } }
export const saveLang = (l) => { try { localStorage.setItem(KEY, l) } catch { /* ignore */ } }

export const STR = {
  hi: {
    idle: 'माइक दबाकर बोलिए', listen: 'सुन रहा हूँ…', think: 'सोच रहा हूँ…', speak: 'बता रहा हूँ', more: 'और कुछ पूछना है?',
    ph: 'बोलिए…', intro: 'हिंदी या English में पूछिए',
    unclear: 'आवाज़ समझ नहीं आई। नीचे से कोई सवाल चुन लीजिए।', silent: 'कुछ सुनाई नहीं दिया। माइक दबाकर फिर से बोलिए।', nomic: 'यहाँ माइक नहीं चल रहा। नीचे से कोई सवाल चुन लीजिए।',
    needLive: 'आवाज़ के लिए Live services चलाइए, या नीचे से कोई सवाल चुनिए।',
    yesSay: 'या बोलिए “हाँ”', nudgeLabel: 'आज का ज़रूरी काम', nudgeCta: 'सबूत की फ़ोटो भेजें', nudgeDemo: 'डेमो देखें',
    up: 'फ़ोटो भेजें', ask: 'बोलकर और पूछिए', stop: 'बोल चुका, भेजिए', menu: 'सारी मदद', khata: 'खाता', askVoice: 'बोलकर पूछें', typePh: 'या यहाँ लिखिए…', send: 'भेजें', cUnclear: 'फिर से पूछिए', cBooks: 'आपके खाते से',
    asH: 'क्या भेजना है?', asPodT: 'डिलीवरी का सबूत', asPodS: 'ग्राहक को सामान मिल गया — रसीद या फ़ोटो', asShotT: 'UPI पेमेंट का स्क्रीनशॉट', asShotS: 'ग्राहक ने पेमेंट दिखाया — असली है या नकली जाँचें',
    asNote: 'कैमरा से फ़ोटो लें या गैलरी से चुनें', cancel: 'रद्द करें', mute: 'आवाज़ बंद करें', unmute: 'आवाज़ चालू करें',
    p_settle: 'पैसा कहाँ कटा?', p_utr: 'UTR जाँचें', p_cb: 'डिलीवरी प्रूफ भेजें', p_hold: 'सेटलमेंट होल्ड', p_edi: 'लोन EDI फेल', p_dup: 'दो बार पैसा कटा', p_growth: 'धंधा कैसे बढ़ाएँ',
    nTitleCb: (o, a) => `${o} का ₹${a} रुका हुआ है`, nTextCb: 'डिलीवरी का सबूत भेजिए, पैसा 48 घंटे में छूट जाएगा।', nTitleSt: 'आज का हिसाब देखें', nTextSt: 'सेटलमेंट में कितना कटा, एक बटन में जानिए।',
    attn: 'ध्यान दीजिए', attnSub: 'क्या हुआ और अब क्या करना है', clear: 'सब ठीक है', clearSub: 'अभी कोई ज़रूरी काम बाकी नहीं है', handled: 'हो गया', showAll: 'सभी देखें', showLess: 'कम दिखाएँ',
    cHold: 'हो गया', cWait: 'आपकी मंज़ूरी चाहिए', cTeam: 'टीम को भेजा', cFake: 'नकली लगता है', cPend: 'पेंडिंग',
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
    gross: 'कुल बिक्री', net_bank_credit: 'बैंक में आया', variance: 'कुल कटौती', utr: 'UTR', utr_number: 'UTR', amount: 'रकम', amount_inr: 'रकम', payer_app: 'पेमेंट ऐप', order_id: 'ऑर्डर',
    outstanding: 'बाकी लोन', payable: 'भरना है', foreclosure_charge: 'क्लोज़र चार्ज', noc_eta_days: 'NOC (दिन)', pickup_ticket: 'टिकट', ticket: 'टिकट', release_eta: 'पैसा कब मिलेगा',
    edi_saved_inr: 'बचत', order_amount_inr: 'ऑर्डर रकम', projected_net_payout: 'कल का payout', duplicates_found: 'डुप्लिकेट', pickup_within_hours: 'पिकअप (घंटे)', eta_hours: 'समय (घंटे)', current_account: 'बैंक खाता', lender: 'लोन देने वाला', settlement_date: 'तारीख',
  },
  en: {
    gross: 'Total sales', net_bank_credit: 'Credited to bank', variance: 'Total deductions', utr: 'UTR', utr_number: 'UTR', amount: 'Amount', amount_inr: 'Amount', payer_app: 'Payment app', order_id: 'Order',
    outstanding: 'Loan balance', payable: 'To pay', foreclosure_charge: 'Closure charge', noc_eta_days: 'NOC (days)', pickup_ticket: 'Ticket', ticket: 'Ticket', release_eta: 'Money released',
    edi_saved_inr: 'You save', order_amount_inr: 'Order amount', projected_net_payout: 'Tomorrow’s payout', duplicates_found: 'Duplicates', pickup_within_hours: 'Pickup (hours)', eta_hours: 'Time (hours)', current_account: 'Bank account', lender: 'Lender', settlement_date: 'Date',
  },
}
export const STATUS = {
  hi: { PENDING: 'पेंडिंग', SUCCESS: 'सफल', RELEASED: 'छूट गया', RESOLVED: 'हल हो गया', RECONCILED: 'हिसाब मिल गया', PROCESSED: 'हो गया', NOT_FOUND_SUSPECTED_FAKE: 'नकली लगता है', ESCALATED: 'टीम को भेजा', RETURN_INITIATED: 'पिकअप तय', FORECLOSURE_QUOTE_READY: 'कोट तैयार', KYC_UPDATE_LINK_SENT: 'लिंक भेजा', NO_BANK_HOLD: 'कोई होल्ड नहीं', ACTION_REQUIRED: 'आपकी मंज़ूरी चाहिए', ALERT_RAISED: 'आपकी मंज़ूरी चाहिए', EDI_PAUSED: 'EDI रुका', REFUND_INITIATED: 'रिफंड शुरू' },
  en: { PENDING: 'Pending', SUCCESS: 'Successful', RELEASED: 'Released', RESOLVED: 'Resolved', RECONCILED: 'Reconciled', PROCESSED: 'Processed', NOT_FOUND_SUSPECTED_FAKE: 'Looks fake', ESCALATED: 'Sent to team', RETURN_INITIATED: 'Pickup scheduled', FORECLOSURE_QUOTE_READY: 'Quote ready', KYC_UPDATE_LINK_SENT: 'Link sent', NO_BANK_HOLD: 'No hold', ACTION_REQUIRED: 'Needs your OK', ALERT_RAISED: 'Needs your OK', EDI_PAUSED: 'EDI paused', REFUND_INITIATED: 'Refund started' },
}

