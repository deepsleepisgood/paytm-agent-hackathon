"""Live check of /llm against real Sarvam (service running on :8001 with a key).

    python scripts/live_intents.py

Part 1: the 8 plan.md intents (+ slots), reasoning off.
Part 2: one Option A/B/C intervention evaluation, reasoning off vs "low", to see whether
        multi-step reasoning fits inside the 5 s budget (Person 3 times out at 6 s).
"""
import json
import time

import httpx

URL = "http://localhost:8001/llm"
INTENTS = ("MANDATE_TROUBLESHOOT, SETTLEMENT_RECONCILE, CHARGEBACK_RESOLVE, UTR_VERIFY, "
           "DUPLICATE_RECONCILE, GROWTH_ADVISORY, CASHFLOW_EDI_SWITCH, ESCALATE_HUMAN")
SYS = (f"You route Paytm merchant messages. Return JSON with keys: intent (one of {INTENTS}), "
       "utr_number, order_id, amount. Use null when a value is not mentioned. "
       "Hardware/Soundbox faults and requests for a person are ESCALATE_HUMAN. "
       "Questions about pausing EDI because cash is short are CASHFLOW_EDI_SWITCH.")

TESTS = [
    ("Mera ₹500 ka loan EDI mandate fail ho gaya", {"MANDATE_TROUBLESHOOT"}),
    ("Bhaiya kal ka settlement 4160 kam kyun aaya?", {"SETTLEMENT_RECONCILE"}),
    ("मेरे बैंक में पैसा कम आया है", {"SETTLEMENT_RECONCILE"}),
    ("Order 9981 pe chargeback hold kyun laga?", {"CHARGEBACK_RESOLVE"}),
    ("Customer bol raha UTR 632184920111 se 1250 bheja, check karo", {"UTR_VERIFY"}),
    ("Customer ne ek hi order ke liye do baar payment kar diya", {"DUPLICATE_RECONCILE"}),
    ("Mere pichle 6 mahine ke data se business badhane ka suggestion do", {"GROWTH_ADVISORY"}),
    ("Refund ke baad kal ka payout bahut kam hai, supplier ko 4500 dena hai, EDI rok sakte ho?", {"CASHFLOW_EDI_SWITCH"}),
    ("Mera Soundbox kharab ho gaya, awaaz nahi aa rahi", {"ESCALATE_HUMAN"}),
    ("Mujhe kisi insaan se baat karni hai abhi", {"ESCALATE_HUMAN"}),
    # Real voice note from earlier testing. Vague on purpose: either answer is reasonable.
    ("मुझे जानना है कि जो मेरा पेमेंट है वो सही से प्रोसेस हुआ या नहीं।", {"UTR_VERIFY", "SETTLEMENT_RECONCILE"}),
]

print("Part 1: intent + slots (reasoning off)\n")
ok = 0
for text, want in TESTS:
    t = time.perf_counter()
    r = httpx.post(URL, timeout=10, json={"system_prompt": SYS, "user_prompt": text, "response_format": "json"}).json()
    p = r.get("parsed") or {}
    hit = p.get("intent") in want
    ok += hit
    ms = int((time.perf_counter() - t) * 1000)
    print(f"{'PASS' if hit else 'FAIL'} {ms:>5}ms [{r.get('source')}] {p.get('intent')} "
          f"utr={p.get('utr_number')} order={p.get('order_id')} amt={p.get('amount')}  <- {text}")
print(f"\n{ok}/{len(TESTS)} correct\n")

EVAL_SYS = (
    "You are a Paytm merchant's AI buddy. Merchant history: daily_avg_sales 32000, weekend_multiplier 2.3x, "
    "past_edi_success_rate 96%, daily_edi 500, loan_balance 42000, kfs_edi_holiday_eligible true, "
    "sales dipped 40% this week due to rain. Diagnose the root cause (friction vs unwillingness), evaluate "
    "Option A (send reminder), Option B (1-tap UPI link or 48h KFS EDI pause), Option C (escalate). "
    'Return JSON: {"root_cause": str, "options": [{"id": "A"|"B"|"C", "score": 0-1, "rationale": str}], '
    '"selected_option": str, "reply_text": "warm Hinglish, max 35 words"}'
)
print("Part 2: Option A/B/C evaluation (mandate failed)\n")
for effort in ("none", "low"):
    t = time.perf_counter()
    r = httpx.post(URL, timeout=10, json={"system_prompt": EVAL_SYS, "user_prompt": "Mera ₹500 ka EDI mandate fail ho gaya",
                                          "response_format": "json", "reasoning_effort": effort}).json()
    p = r.get("parsed") or {}
    ms = int((time.perf_counter() - t) * 1000)
    print(f"reasoning={effort:<4} {ms:>5}ms [{r.get('source')}] root_cause={p.get('root_cause')} "
          f"selected={p.get('selected_option')}")
    print(f"           reply: {p.get('reply_text')}\n")
print("If 'low' shows [mock] or > 5000 ms, Person 3 should keep reasoning off for this call.")
