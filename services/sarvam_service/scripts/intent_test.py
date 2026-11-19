"""Live intent-routing check against /llm (run with the service up on :8001).

    python scripts/intent_test.py
"""
import time

import httpx

SYS = ("You route Paytm merchant messages. Return JSON with keys: intent (one of SETTLEMENT_RECONCILE, "
       "UTR_VERIFY, CHARGEBACK_RESOLVE, REFUND_MANAGE, FEE_GST_LOAN, ESCALATE_HUMAN), utr_number, order_id, amount. "
       "Use null when a value is not mentioned.")

TESTS = [
    ("Bhaiya kal ka settlement 4160 kam kyun aaya?", {"SETTLEMENT_RECONCILE"}),
    ("मेरे बैंक में पैसा कम आया है", {"SETTLEMENT_RECONCILE"}),
    ("Customer bol raha UTR 632184920111 se 1250 bheja, check karo", {"UTR_VERIFY"}),
    ("Order 9981 pe chargeback hold kyun laga?", {"CHARGEBACK_RESOLVE"}),
    ("Order 4412 ka refund kab gaya customer ko?", {"REFUND_MANAGE"}),
    ("GST 261 rupaye kyun kata, ITC milega kya?", {"FEE_GST_LOAN"}),
    ("Loan ki kisht kal kitni kategi?", {"FEE_GST_LOAN"}),
    ("Mujhe kisi insaan se baat karni hai abhi", {"ESCALATE_HUMAN"}),
    # Real voice note from Test 3. Vague on purpose: either answer is reasonable.
    ("मुझे जानना है कि जो मेरा पेमेंट है वो सही से प्रोसेस हुआ या नहीं।", {"UTR_VERIFY", "SETTLEMENT_RECONCILE"}),
]

ok = 0
for text, want in TESTS:
    t = time.perf_counter()
    r = httpx.post("http://localhost:8001/llm", timeout=10, json={
        "system_prompt": SYS, "user_prompt": text, "response_format": "json"}).json()
    p = r.get("parsed") or {}
    hit = p.get("intent") in want
    ok += hit
    ms = int((time.perf_counter() - t) * 1000)
    print(f"{'PASS' if hit else 'FAIL'} {ms:>5}ms [{r.get('source')}] {p.get('intent')} "
          f"utr={p.get('utr_number')} order={p.get('order_id')} amt={p.get('amount')}  <- {text}")
print(f"\n{ok}/{len(TESTS)} correct")
