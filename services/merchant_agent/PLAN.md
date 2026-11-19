# Build for Bharat Hackathon — Master Execution Plan (`plan.md`)

> Team master plan, copied here as context for the Merchant Agent (Person 3). The canonical copy belongs at the repo root.

**Event:** Masters' Union School of AI Hackathon (Paytm $\times$ Sarvam AI) — Gurugram  
**Track:** Track 3 — Autonomous AI Teammates  
**MVP Freeze Deadline:** Thursday, 19 Nov 2026 — **21:00 IST (9:00 PM)**  
**Day 2 Sell Sprint & Pitch:** Friday, 20 Nov 2026 — **09:00 to 18:00 IST**

---

## 1. Core Concept & Track 3 Positioning

### What We Are Building
An **Agent-to-Agent (A2A) Merchant–Paytm Resolution Network** featuring two autonomous AI teammates that sit on opposite sides of the data boundary and negotiate structured, consent-verified resolutions in seconds:

1. **Merchant AI Teammate (Merchant Side):** Lives with the merchant (Hindi/Hinglish voice + document upload), enforces explicit **DPDP consent**, tracks local order sheets and **GST Input Tax Credit (ITC)**, and dispatches structured A2A requests.
2. **Paytm AI Teammate (Acquirer Side):** Lives on Paytm’s acquiring settlement ledger, validates consent tokens, reconciles settlement deductions, verifies 12-digit UTRs across all payer UPI apps (GPay, PhonePe, Paytm, BHIM), processes Proof of Delivery (PoD) to release chargeback holds, and escalates hardware/high-value edge cases to L2 human support.

### Why This Wins Track 3
* **Outcome Over Chatbot:** Resolves full end-to-end customer service & settlement workflows (zero manual CSV reconciliation, automated chargeback PoD collection, instant fake-screenshot fraud blocking).
* **Regulatory & Data-Boundary Native:** Respects RBI Digital Lending/Payments guidelines and the **DPDP Act**—no raw phone-number scraping, explicit timestamped consent tokens on every A2A hop, and strict separation between merchant books and Paytm's internal ledger.
* **Wedge-to-Teammate Vision:** Starts with the sharpest, highest-anxiety wedge (settlement variances, stuck UPI payments, and chargeback holds) and expands into the merchant's full 24/7 vernacular operations teammate.

---

## 2. Verified Market Sizing (For Day 2 Pitch Deck)

| Metric | Verified Figure | Primary Source |
| :--- | :--- | :--- |
| **Monthly UPI Scale** | **25.47 billion** txns worth **₹31.53 lakh crore** (Oct 2026) | NPCI UPI Product Statistics (Nov 2026) |
| **Annual UPI Scale** | **24,162 crore** txns worth **₹314.23 lakh crore** (FY25–26) | PIB / Ministry of Finance (July–Aug 2026) |
| **Paytm Merchant Network** | **4 crore+ (40M+)** MSME merchants on Paytm QR/Acquiring | Paytm (One97) Q1 FY26 Earnings Release |
| **Digital Payment Frauds** | **24 lakh** cases (2024) $\rightarrow$ **28 lakh** cases (**₹22,931 Cr**) in 2025 | RBI Discussion Paper (Apr 2026), citing NCRP |
| **True Merchant Dispute Cost** | Every **₹1** of fraud/dispute costs Indian merchants **₹4** total | LexisNexis (cited via Razorpay, Aug 2026) |

---

## 3. System Architecture & Tech Stack

### Hackathon MVP Stack (Shipping by 9:00 PM)
* **Speech-to-Text (STT):** Sarvam `Saaras v4` (`mode="codemix"` for noisy Hindi/Hinglish shop audio).
* **Text-to-Speech (TTS):** Sarvam `Bulbul v4 Flash` (fallback `bulbul:v3`, `hi-IN`).
* **Reasoning & Intent Routing:** Sarvam `Sarvam-105B` (`/chat/completions`, JSON mode) + deterministic keyword fallbacks.
* **Document Intelligence:** Sarvam `Vision 2.1` (`POST /doc-ai/v1/job/extract` via `sarvamai` SDK) for PoD receipts & UPI screenshots.
* **Backend Microservices:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, async `httpx`, in-memory state with 1-click `/reset`.
* **Frontend:** React (Vite or Next.js), Tailwind CSS, native browser `MediaRecorder API`.

### Production Scale-Up Story (For VC & Paytm Q&A)
* **Latency:** Swap LLM router for **Sarvam Prism** (~44ms System-1 routing).
* **Transport:** Upgrade HTTP polling to **WebSockets/SSE** + **Apache Kafka** for async settlement/chargeback webhooks.
* **Security:** Upgrade mock consent tokens to **mTLS + OAuth 2.0/JWT** scoped per MID + PostgreSQL immutable DPDP Consent Ledger.
* **Distribution:** Deploy the exact same Merchant Agent (`8003`) inside **WhatsApp Business API** and **Paytm for Business App**.

---

## 4. Repo Structure & Team Ownership (Zero Merge Conflicts)

Every team member works on their own branch and **strictly only edits their assigned folder**.

```text
a2a-paytm-teammates/
├── plan.md                      <-- This master plan
├── CONTRACT.md                  <-- Frozen API & seed-data contract (read-only)
├── services/
│   ├── sarvam_service/          <-- Person 1 (Port 8001 | branch: feat/sarvam)
│   ├── paytm_agent/             <-- Person 2 (Port 8002 | branch: feat/paytm-agent)
│   └── merchant_agent/          <-- Person 3 (Port 8003 | branch: feat/merchant-agent)
└── frontend/                    <-- Person 4 (Port 3000 | branch: feat/frontend)
```

| Role | Owner | Port | Core Responsibility |
| :--- | :--- | :--- | :--- |
| **Person 1** | Sarvam AI Wrapper | `8001` | `/stt`, `/tts`, `/llm`, `/doc-extract` (`pod` & `upi_screenshot`) + `MOCK_MODE` & <8s fallback. |
| **Person 2** | Paytm AI Teammate | `8002` | Acquiring settlement ledger, DPDP 403 guardrail, `/a2a/dispatch` for all 6 intents, `/ledger/{mid}`, `/ledger/reset`. |
| **Person 3** | Merchant AI Teammate (Glue) | `8003` | Intent router + keyword fallback, DPDP consent minting, A2A orchestration, local GST ITC logging, Hinglish voice formatting, `/events`, `/reset`. |
| **Person 4** | 3-Column Demo UI | `3000` | Left: Mobile Voice/Doc App + Preset Chips; Center: Live A2A & DPDP Bus; Right: Paytm Ledger & KPI Command Center. |

---

## 5. Frozen Data & Intent Contract

### The 6 Supported Merchant Intents
1. `SETTLEMENT_RECONCILE`: Explain net payout vs. gross sales variance (MDR, GST, refunds, Soundbox, chargeback hold).
2. `UTR_VERIFY`: Verify 12-digit UTR from voice or GPay/PhonePe screenshot (`SUCCESS`, `PENDING`, or `NOT_FOUND_SUSPECTED_FAKE`).
3. `CHARGEBACK_RESOLVE`: Extract Proof of Delivery (`pod`), submit A2A to Paytm, release `HELD` $\rightarrow$ `RELEASED`.
4. `REFUND_MANAGE`: Check status of `ORDER #4412` (`PROCESSED`) or auto-initiate refund ($\le ₹5,000$ autonomous; $> ₹5,000$ human escalation).
5. `FEE_GST_LOAN`: Itemized MDR rates (Credit Card 2%, Wallet-on-UPI >₹2k 1.1%, Bank UPI 0%), GST ITC (`₹261`), and Merchant Loan EDI (`₹500/day`, balance `₹42,000`).
6. `ESCALATE_HUMAN`: Hardware issues (Soundbox) or disputes $> ₹5,000$ $\rightarrow$ creates pre-filled L2 ticket (`TKT-PAYTM-xxxx`).

### Unified Seed Data (MID: `PAYTM_MERCH_8821` — "Sharma Electronics")
* **Settlement Date:** `2026-11-18`
* **Expected Gross:** `₹1,00,000` | **Net Bank Credit:** `₹95,840` | **Variance:** `₹4,160`
  * `MDR_FEE`: `₹1,450` (2% on ₹50k CC + 1.1% on ₹25k Wallet-on-UPI >₹2k + 0% on ₹25k Bank UPI)
  * `GST_ON_MDR`: `₹261` (18% GST — auto-logged to merchant ITC sheet)
  * `CUSTOMER_REFUND`: `₹1,500` (`ORDERID #4412`, `PROCESSED`)
  * `SOUNDBOX_RENTAL`: `₹149` (Monthly fee)
  * `CHARGEBACK_HOLD`: `₹800` (`TXNID #9981`, `ORDERID #9981`, initial status `HELD`, PoD due in 48h)
* **Recent UPI UTR Ledger:**
  * `632184920111` | `₹1,250` | GPay | `SUCCESS` (Settled)
  * `632184920999` | `₹2,400` | PhonePe | `PENDING` (NPCI T+1 auto-reversal)
  * Any unknown/tampered UTR | `NOT_FOUND_SUSPECTED_FAKE` (Increments `frauds_blocked_count`)

### Endpoint Summary (All Services Enable CORS for `http://localhost:3000`)
* **Port `8001` (Sarvam):** `POST /stt`, `POST /tts`, `POST /doc-extract`, `POST /llm`
* **Port `8002` (Paytm):** `GET /ledger/{mid}`, `POST /a2a/dispatch`, `POST /ledger/reset`
* **Port `8003` (Merchant):** `POST /merchant/query`, `POST /merchant/query-audio`, `POST /merchant/upload-doc`, `GET /events`, `POST /reset`

---

## 6. Hour-by-Hour Timeline (Now $\rightarrow$ 9:00 PM Freeze)

* **3:55 PM – 5:30 PM | Parallel Build Sprint:**
  * All 4 teammates build & unit-test their respective ports standalone using mocks/fallbacks.
  * Person 3 tunes Hinglish system prompts ($\le 35$ words / 2 sentences per reply) and verifies `test_merchant.py` passes all 6 intents.
* **5:30 PM – 5:45 PM | Contract Police Check (Led by Person 3):**
  * 15-minute sync across all 4 teammates to verify exact JSON keys match `CONTRACT.md` character-for-character (especially `audio_base64`, `utr_number`, `doc_type`, and WebM/WAV audio handling).
* **5:45 PM – 6:30 PM | Final Polish Before Merge:**
  * Fix any schema mismatches, push feature branches, and prepare sample `pod_9981.png` and `fake_upi.png` test files.
* **6:30 PM – 7:30 PM | Master Integration Hour (On 1 Demo Laptop):**
  * Pull all 4 branches onto the master demo machine.
  * Boot `8001`, `8002`, `8003`, `3000` simultaneously (with `SARVAM_SERVICE_URL` and `PAYTM_AGENT_URL` configured via `.env`).
  * Verify Golden Path + Fake Screenshot Path + Escalation Path + 1-click Reset.
* **7:30 PM – 8:30 PM | Demo Hardening & Backup Recording:**
  * Test noisy-room preset buttons and real mic audio.
  * Record a clean 60-second screen capture of the full working flow as an emergency backup.
  * Expose backend/frontend via public tunnel (`ngrok` / Render / Vercel) for tomorrow's mobile field testing.
* **8:30 PM – 9:00 PM | MVP Freeze & Submission:**
  * Lock repo, verify live URL, submit before **21:00 IST**.

---

## 7. Live Demo Script (2-Minute Golden Path for Judges)

1. **Setup:** Show the 3-column screen. Point out **Left** (Merchant Hindi Voice App), **Center** (Live A2A & DPDP Compliance Bus), **Right** (Paytm Acquiring Ledger).
2. **Step 1 — Settlement Variance (Voice / Preset 1):**
   * Trigger: *"Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?"*
   * **What Judges See:** DPDP consent minted (Center) $\rightarrow$ Merchant Agent sends A2A JSON to Paytm Agent $\rightarrow$ Paytm returns itemized breakdown $\rightarrow$ ₹261 GST ITC auto-logged $\rightarrow$ App speaks crisp Hindi reply flagging the ₹800 chargeback hold on `#9981`.
3. **Step 2 — Autonomous Chargeback Resolution:**
   * Tap **"Haan, Delivery Proof Bhejo (Order #9981)"** (uploads `pod_9981.png`).
   * **What Judges See:** Sarvam Vision extracts `order_id: #9981, DELIVERED` $\rightarrow$ A2A `CHARGEBACK_RESOLVE` sent $\rightarrow$ Right Panel animates `#9981` from **Amber (`HELD`)** to **Emerald (`RELEASED — T+1`)** $\rightarrow$ `Tickets Deflected` increments.
4. **Step 3 — Fake UPI Screenshot Fraud Catch:**
   * Trigger **Fake Screenshot Check** (uploads `fake_upi.png`).
   * **What Judges See:** Sarvam Vision extracts tampered UTR $\rightarrow$ Paytm Ledger returns `NOT_FOUND_SUSPECTED_FAKE` $\rightarrow$ Urgent Hindi audio alert warns merchant not to hand over goods $\rightarrow$ `Frauds Blocked` increments.
5. **Reset:** Click **"Reset Demo"** in top-right before the next judge approaches.

---

## 8. Day 2 Playbook: 3-Hour Sell Sprint (Friday, 20 Nov)

**Goal:** Put the live MVP in the hands of **15–20 real Gurugram merchants** (Vyapar Kendra, Sector 29, local kiranas, electronics shops, clinics, salons) and bring back hard traction metrics for the Grand Finale pitch.

### Field Script (2 Minutes Per Shop)
1. **Hook:** *"Uncle/Bhaiya, aap Paytm QR ya machine use karte ho? Kabhi aisa hua hai ki settlement kam aaya ya customer ne fake UPI screenshot dikhaya?"*
2. **Live Test:** Hand them the phone/tablet, let them speak a Hindi question or tap the ₹4,160 / fake screenshot demo, and watch them react to the Hindi voice breakdown.
3. **Capture Proof (Track in a Google Sheet):**
   * Shop Name, Category, Owner Name, and Monthly Paytm Volume (approx.).
   * **The 3 Traction Metrics to Log:**
     1. Number of merchants who completed a live voice/doc test.
     2. Number who signed up for the WhatsApp pilot (collect phone/consent or WhatsApp opt-in).
     3. 2–3 verbatim Hindi quotes on their biggest pain point (put these on Slide 2 of your Grand Finale deck).
