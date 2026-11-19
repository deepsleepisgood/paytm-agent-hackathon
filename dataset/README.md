# Dataset — A2A Merchant–Paytm Resolution Network

Single source of truth for demo data (MID `PAYTM_MERCH_8821`, Sharma Electronics). Mirrors `contract.md` / `plan.md` section 5.

```
dataset/
├── seed/
│   ├── merchant.json          merchant profile, Soundbox device
│   ├── settlement.json        2026-11-18 settlement, gross mix, 5 deductions
│   ├── transactions.json      UPI/UTR ledger for UTR_VERIFY
│   ├── refunds_orders.json    ORDER #4412 refund, #9981 chargeback, ₹5,000 refund policy
│   ├── loan.json              EDI ₹500/day, balance ₹42,000
│   ├── fee_rules.json         MDR rates + 18% GST
│   └── initial_state.json     reset target (HELD, counters 0, empty logs)
├── intents/utterances.json    Hinglish/Hindi phrases per intent (`preset: true` = UI chips)
├── golden/golden_paths.json   expected outcomes for the 2-minute demo
└── test_files/                pod_9981.png, fake_upi.png (placeholders, see generate_test_files.py)
```

## Known inconsistency to resolve (team decision)
`MDR_FEE = ₹1,450` but the stated mix (2% × ₹50k + 1.1% × ₹25k + 0% × ₹25k) computes to **₹1,275** (₹175 short).
GST (18% of ₹1,450 = ₹261) and the ₹4,160 total only work with ₹1,450, so the contract value is kept.
Pick one story before the demo (e.g. adjust the mix or call ₹175 "other fees") so a judge doing the maths does not catch it.

## Usage
- Paytm agent (8002) and Merchant agent (8003) can load `seed/*` on startup and on reset.
- Frontend (3000) can import preset chips from `intents/utterances.json`.
- Placeholders only: `fake_upi.png` uses a made-up UTR; replace both PNGs with realistic screenshots before demo day.
