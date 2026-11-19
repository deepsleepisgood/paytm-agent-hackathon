"""Short live eval of the Merchant AI Buddy: does it understand the question, answer THAT question with the right
fact, in the language the app asked for, quickly?  Run with the stack up:

    python run.py eval                                     (starts everything, runs this, stops)
    python services/merchant_agent/eval_live.py --base http://127.0.0.1:8003

Each case: the question, the language tab, the acceptable intents, and facts the answer must contain (any of).
Facts come from data/seed (as of 2026-11-19): next settlement 20 Nov ~08:00, yesterday's sales ₹22,301,
loan balance ₹42,000, deductions ₹4,160, Soundbox rent ₹149, UTR …111 = ₹1,250 genuine, UTR …555 = not found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request

DEV = re.compile("[ऀ-ॿ]")
INFO_OR_FEE = ("INFO_QUERY", "FEE_GST_LOAN")
CASES = [
    # (language, question, acceptable intents, answer must contain any of)
    ("hi", "मेरा अगला settlement कब आएगा?", ("INFO_QUERY",), ("20", "कल")),
    ("hi", "kal kitni sale hui thi?", INFO_OR_FEE, ("22,301", "22301")),
    ("hi", "Loan ka kitna paisa baaki hai?", INFO_OR_FEE, ("42,000", "42000")),
    ("hi", "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?", ("SETTLEMENT_RECONCILE",), ("4,160",)),
    ("hi", "UTR 632184920111 ka payment aaya kya?", ("UTR_VERIFY",), ("1,250",)),
    ("hi", "UTR 632184920555 check karo, customer screenshot dikha raha hai", ("UTR_VERIFY",), ("मत", "नहीं मिला", "fake")),
    ("hi", "Order 9981 ka chargeback wala paisa kab milega?", ("CHARGEBACK_RESOLVE",), ("800",)),
    ("hi", "Customer ne galti se do baar payment kar diya", ("DUPLICATE_RECONCILE",), ("1,180",)),
    ("hi", "Mera loan EDI bounce ho gaya, ab kya karun?", ("MANDATE_TROUBLESHOOT",), ("500",)),
    ("hi", "Soundbox kharab hai, payment aane pe awaaz nahi aati", ("ESCALATE_HUMAN",), ("tkt", "ticket", "TKT")),
    ("hi", "Soundbox ka rent kitna katta hai?", INFO_OR_FEE, ("149",)),
    ("hi", "Business badhane ka koi suggestion do", ("GROWTH_ADVISORY",), ("गुरुवार", "Thursday", "stock")),
    ("hi", "Aaj cricket match kaun jeeta?", ("UNCLEAR",), ("समझ नहीं",)),
    ("hi", "Mujhe ek pizza order karna hai", ("UNCLEAR",), ("समझ नहीं",)),
    ("en", "When will my next settlement come?", ("INFO_QUERY",), ("20", "tomorrow")),
    ("en", "Why was ₹4,160 deducted from yesterday's settlement?", ("SETTLEMENT_RECONCILE",), ("4,160",)),
    ("en", "How much did I sell yesterday?", INFO_OR_FEE, ("22,301", "22301")),
    ("en", "Is UTR 632184920555 a real payment?", ("UTR_VERIFY",), ("not", "don't", "Do not")),
    ("en", "My loan EDI bounced, what should I do?", ("MANDATE_TROUBLESHOOT",), ("500",)),
    ("en", "A customer paid me twice for the same order", ("DUPLICATE_RECONCILE",), ("1,180",)),
    ("en", "How much of my loan is still left to pay?", INFO_OR_FEE, ("42,000", "42000")),
    ("en", "What's the weather like today?", ("UNCLEAR",), ("Sorry",)),
    ("en", "Tell me a joke", ("UNCLEAR",), ("Sorry",)),
]


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8003")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    post(f"{args.base}/reset?cascade=true", {})
    rows, t_all = [], []
    for lang, q, intents, must in CASES:
        t0 = time.time()
        try:
            b = post(f"{args.base}/merchant/query", {"text": q, "mid": "PAYTM_MERCH_8821", "consent_granted": True,
                                                    "language": lang})
        except Exception as exc:  # noqa: BLE001
            b = {"intent": f"ERROR {exc}", "reply_text": ""}
        dt = time.time() - t0
        t_all.append(dt)
        reply = b.get("reply_text") or ""
        ok_intent = b.get("intent") in intents
        ok_fact = any(m in reply for m in must)
        ok_lang = bool(DEV.search(reply)) if lang == "hi" else not DEV.search(reply)
        rows.append((lang, q, b.get("intent"), ok_intent, ok_fact, ok_lang, dt, b.get("reply_source"), reply))
    print()
    for lang, q, intent, oi, of, ol, dt, src, reply in rows:
        mark = "PASS" if oi and of and ol else "FAIL"
        print(f"{mark} [{lang}] {q[:52]:<52} -> {intent:<20} intent:{'ok' if oi else 'X'} fact:{'ok' if of else 'X'} "
              f"lang:{'ok' if ol else 'X'} {dt:4.1f}s [{src}]")
        print(f"       {reply[:170]}")
    n = len(rows)
    acc = lambda i: sum(r[i] for r in rows)  # noqa: E731
    full = sum(1 for r in rows if r[3] and r[4] and r[5])
    print(f"\n  intent correct   {acc(3)}/{n}\n  answers the question (right fact)   {acc(4)}/{n}\n"
          f"  right language   {acc(5)}/{n}\n  all three        {full}/{n}\n"
          f"  latency          avg {sum(t_all) / n:.1f}s, max {max(t_all):.1f}s")
    return 0 if full == n else 1


if __name__ == "__main__":
    sys.exit(main())
