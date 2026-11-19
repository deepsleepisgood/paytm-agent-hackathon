# Build for Bharat — Master Architecture & Execution Plan (`plan.md`, V3)

> Team master plan, copied here as context for the Merchant AI Buddy (Person 3). The canonical copy belongs at the repo root.
> This V3 replaces the earlier plan. The Person 3 briefs that came with it are at the bottom.

**Event:** Masters' Union School of AI Hackathon (Paytm $\times$ Sarvam AI) — Gurugram
**Track:** Track 3 — Autonomous AI Teammates
**Architecture Paradigm:** Two-Tier Autonomous Merchant Operating System (Merchant AI Buddy $\leftrightarrow$ Paytm 4-Agent Resolution Mesh)

---

## 1. Core Vision & Two-Tier Architecture

Instead of a reactive single-purpose support bot, we are building a **Closed-Loop, Goal-Oriented Multi-Agent System** that sits on both sides of the merchant–acquirer boundary:

1. **Frontend Tier — All-in-One Merchant AI Buddy (`services/merchant_agent` | Port `8003`):**
   * Lives with the merchant inside *Paytm for Business* in natural Hindi/Hinglish voice and text.
   * **Historical Memory & Business Intelligence:** Analyzes 6 months of local sales, peak-day multipliers, supplier payables, and past dispute history to give proactive CFO/growth advice.
   * **Root-Cause Friction Diagnosis:** Distinguishes *payment friction* (e.g., mandate failure, temporary rain/holiday cash dip) from *unwillingness*, evaluates multiple candidate interventions (`Option A vs. B vs. C`), and selects the highest-ROI, DPDP-consented action.
2. **Backend Tier — Paytm Multi-Agent Mesh (`services/paytm_agent` | Port `8002`):**
   * A central **Paytm Master Orchestrator** that enforces DPDP consent tokens and coordinates **4 specialized solver sub-agents**:
     1. **Intelligence & Root-Cause Agent:** Investigates UTRs, settlement deductions, and mandate bounce reasons.
     2. **Risk & Policy Engine:** Evaluates RBI Digital Lending KFS clauses, autonomous refund limits ($\le ₹5,000$), and hardship eligibility.
     3. **Resolution & Friction-Removal Agent:** Releases chargeback holds upon PoD verification, switches failed mandates to 1-tap UPI links, and executes KFS-compliant EDI pauses.
     4. **Ledger & Learning Operations Agent:** Mutates settlement/loan states and feeds verified outcomes back into future strategy evaluation.

---

## 2. Closed-Loop Cognitive Workflow (5-Step Execution Cycle)

Every merchant interaction or proactive webhook follows this exact verifiable loop:

1. **Understand Merchant (`Merchant Buddy`):** Load merchant profile, 6-month QR/POS sales history, active Loan EDI (`₹500/day`), and supplier payables (`₹4,500` due tomorrow).
2. **Generate & Evaluate Interventions (`Merchant Buddy`):** Compare candidate actions (e.g., *Option A: Send reminder* vs. *Option B: Troubleshoot mandate / 48h KFS EDI pause* vs. *Option C: Escalate to specialist*) against historical outcomes, cost, UX, and policy constraints.
3. **Execute Permitted Intervention (`DPDP Gate + A2A Dispatch`):** Mint timestamped `DPDP_VERIFIED_TS_*` consent token and dispatch structured JSON to the **Paytm Master Orchestrator**.
4. **Multi-Agent Collaborative Resolution (`Paytm 4-Agent Mesh`):** Paytm's 4 sub-agents execute in sequence (`Intelligence` $\rightarrow$ `Risk & Policy` $\rightarrow$ `Resolution` $\rightarrow$ `Ledger Ops`) and return a full `agent_trace`.
5. **Verify Outcome & Learn (`Closed-Loop Feedback`):** Confirm actual ledger/repayment resolution, log verified metrics into `strategy_memory` for future decisions, and deliver a concise, empathetic Hindi/Hinglish voice response via Sarvam TTS.

---

## 3. Top 8 Merchant Problems Solved End-to-End

| # | Merchant Scenario | Intent Key | Merchant AI Buddy (`8003`) | Paytm 4-Agent Mesh (`8002`) |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Mandate Failed / Missed Loan EDI** | `MANDATE_TROUBLESHOOT` | Checks sales history; sees temporary 40% rain/holiday dip—diagnoses *friction, not default*. | **Intelligence** flags eNACH bounce $\rightarrow$ **Risk** approves KFS pause/UPI switch $\rightarrow$ **Resolution** sends 1-tap UPI link or 48h EDI holiday. |
| **2** | **T+1 Settlement Variance ("₹4,160 kahan kata?")** | `SETTLEMENT_RECONCILE` | Matches local gross sales (`₹1,00,000`) vs. bank credit (`₹95,840`); auto-logs `₹261` GST ITC. | **Intelligence** itemizes MDR, GST, refunds, Soundbox rental, and flags `₹800` chargeback hold (`#9981`). |
| **3** | **Proactive Chargeback Defense (`#9981`)** | `CHARGEBACK_RESOLVE` | Auto-fetches signed PoD from consented Shiprocket connector; asks 1-tap Hindi sign-off. | **Resolution** verifies PoD via Sarvam Vision; **Ledger Ops** flips `#9981` from `HELD` $\rightarrow$ `RELEASED`. |
| **4** | **Stuck / Fake Customer UPI Screenshot** | `UTR_VERIFY` | Extracts 12-digit UTR & tamper flags via Sarvam Vision; warns merchant out loud if fake. | **Intelligence** checks NPCI acquiring logs (`SUCCESS`, `PENDING`, or `NOT_FOUND_SUSPECTED_FAKE`). |
| **5** | **Duplicate Payment / Out-of-Sync Records** | `DUPLICATE_RECONCILE` | Detects customer paid twice for same order in local khata; recommends instant refund. | **Intelligence** matches both UTRs; **Risk** approves ($\le ₹5,000$); **Ledger Ops** executes refund. |
| **6** | **Historical Growth & Credit Advisory** | `GROWTH_ADVISORY` | Analyzes 6-month trend (`2.3x` Friday–Sunday spike); recommends stocking up + working capital line. | **Intelligence + Risk** pre-underwrites transparent KFS credit offer matched to weekend cashflows. |
| **7** | **High Refund vs. Working Capital Crunch** | `CASHFLOW_EDI_SWITCH` | Detects `₹8,500` refund will drop tomorrow's payout (`₹1,200`) below stock payable (`₹4,500`). | **Risk & Resolution** negotiate a 2-day KFS Clause 4.2 EDI pause (`Clix Capital`) saving `₹1,000` liquidity. |
| **8** | **Hardware / Soundbox Fault Escalation** | `ESCALATE_HUMAN` | Runs device battery/network check from historical logs; packages diagnostics. | **Resolution + Ledger Ops** create priority L2 replacement ticket (`TKT-PAYTM-xxxx`) with zero repeat questions. |

---

## 4. Verified Market Sizing (For Pitch Deck)

| Metric | Verified Figure | Primary Source |
| :--- | :--- | :--- |
| **Monthly UPI Volume & Value** | **25.47 billion** txns worth **₹31.53 lakh crore** (Oct 2026) | NPCI UPI Product Statistics (Nov 2026) |
| **Annual UPI Scale** | **24,162 crore** txns worth **₹314.23 lakh crore** (FY25–26) | PIB / Ministry of Finance (July–Aug 2026) |
| **Paytm Merchant Network** | **4 crore+ (40M+)** MSME merchants on Paytm QR/Acquiring | Paytm (One97) Q1 FY26 Earnings Release |
| **Digital Payment Frauds** | **24 lakh** cases (2024) $\rightarrow$ **28 lakh** cases (**₹22,931 Cr**) in 2025 | RBI Discussion Paper (Apr 2026), citing NCRP |
| **True Merchant Dispute Multiplier** | Every **₹1** of fraud/dispute costs Indian merchants **₹4** total | LexisNexis (cited via Razorpay, Aug 2026) |

---

## 5. Tech Stack & Repo Structure

### Core Stack
* **Voice & Indic AI:** Sarvam `Saaras v3` (STT `codemix`), Sarvam `Bulbul v4 Flash` (TTS `hi-IN`), Sarvam `Sarvam-105B` (JSON reasoning & Hinglish advisory), Sarvam `Vision 2.1` (Document AI extraction).
* **Backend Services:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, async `httpx`, in-memory state + `/reset`.
* **Frontend:** React (Vite / Next.js), Tailwind CSS, Web `MediaRecorder API`.

### Folder Ownership (Zero Merge Conflicts)
```text
a2a-paytm-teammates/
├── plan.md                      <-- This master architecture & execution plan
├── CONTRACT.md                  <-- Frozen API & JSON schemas
├── services/
│   ├── sarvam_service/          <-- Person 1 (Port 8001 | branch: feat/sarvam)
│   ├── paytm_agent/             <-- Person 2 (Port 8002 | branch: feat/paytm-agent)
│   └── merchant_agent/          <-- Person 3 (Port 8003 | branch: feat/merchant-agent)
└── frontend/                    <-- Person 4 (Port 3000 | branch: feat/frontend)
```

---

## 6. Frozen API & Seed Data Contract (`CONTRACT.md`)

### Unified Seed Profile (`PAYTM_MERCH_8821` — "Sharma Electronics")
* **6-Month Historical Memory:** `daily_avg_sales: 32000`, `weekend_multiplier: "2.3x (Fri–Sun)"`, `past_edi_success_rate: "96%"`, `tomorrow_stock_payable: 4500`, `active_lender: "Clix Capital"`, `daily_edi: 500`, `loan_balance: 42000`, `kfs_edi_holiday_eligible: true`.
* **Settlement (`2026-11-18`):** Gross `₹1,00,000` | Net Credit `₹95,840` | Variance `₹4,160` (`MDR: ₹1,450`, `GST_ITC: ₹261`, `Refund #4412: ₹1,500`, `Soundbox: ₹149`, `Chargeback Hold #9981: ₹800 [HELD]`).
* **Consented Connectors:** `SHIPROCKET_SYNC` (`ACTIVE`, holds PoD for `#9981`), `VYAPAR_POS_SYNC` (`ACTIVE`), `RBI_ACCOUNT_AGGREGATOR` (`ACTIVE`).
* **UPI UTR Ledger:** `632184920111` (`₹1,250`, GPay, `SUCCESS`), `632184920999` (`₹2,400`, PhonePe, `PENDING`), unknown/tampered UTRs $\rightarrow$ `NOT_FOUND_SUSPECTED_FAKE`.

### Service Endpoints (All Enable CORS for `http://localhost:3000`)
* **Port `8001` (`sarvam_service`):** `POST /stt`, `POST /tts`, `POST /doc-extract` (`doc_type`: `"pod" | "upi_screenshot"`), `POST /llm` (`response_format`: `"text" | "json"`).
* **Port `8002` (`paytm_agent`):**
  * `POST /a2a/dispatch` $\rightarrow$ Accepts `{ "request_id", "mid", "intent", "selected_intervention", "payload", "consent_token" }`, enforces DPDP `403` check, runs the 4 sub-agents, and returns `{ "status", "intent", "agent_trace": [...], "data": {...}, "verified_outcome": {...} }`.
  * `POST /a2a/proactive-alert` $\rightarrow$ Pushes `CHARGEBACK_INCOMING` or `MANDATE_FAILED_ALERT`.
  * `GET /ledger/{mid}` & `POST /ledger/reset`.
* **Port `8003` (`merchant_agent`):**
  * `POST /merchant/query`, `POST /merchant/query-audio`, `POST /merchant/upload-doc`, `POST /merchant/proactive-shield`.
  * Returns `{ "hindi_reply", "audio_base64", "historical_insight", "intervention_evaluation": {...}, "paytm_agent_trace": [...], "a2a_events": [...], "pending_action": {...} | null }`.
  * `GET /events` & `POST /reset`.

---

## 7. Team Coding Prompts (Ready to Copy-Paste)

### Person 1 — Sarvam AI Wrapper (`services/sarvam_service` | Port `8001`)
> Read `plan.md` and `CONTRACT.md`. You ONLY own `/services/sarvam_service` on Port `8001`. Build `/stt` (`saaras:v3`, `codemix`), `/tts` (`bulbul:v4-flash`, `hi-IN`), `/llm` (`sarvam-105b`, supporting `response_format="json"`), and `/doc-extract` (`pod` and `upi_screenshot`, supporting `use_sample_connector=true`). Include `MOCK_MODE=true` and automatic `<6s` timeout fallbacks so downstream services never block.

### Person 2 — Paytm 4-Agent Resolution Mesh (`services/paytm_agent` | Port `8002`)
> Read `plan.md` and `CONTRACT.md`. You ONLY own `/services/paytm_agent` on Port `8002`. Refactor `POST /a2a/dispatch` into a **Paytm Master Orchestrator** that validates `consent_token` (`403` if missing) and visibly runs 4 sub-agents (`IntelligenceAgent`, `RiskPolicyAgent`, `ResolutionAgent`, `LedgerOpsAgent`), returning an `agent_trace` array with each agent's step and output. Support all 8 intents in `plan.md` (`MANDATE_TROUBLESHOOT`, `SETTLEMENT_RECONCILE`, `CHARGEBACK_RESOLVE`, `UTR_VERIFY`, `DUPLICATE_RECONCILE`, `GROWTH_ADVISORY`, `CASHFLOW_EDI_SWITCH`, `ESCALATE_HUMAN`), plus `POST /a2a/proactive-alert`, `GET /ledger/{mid}`, and `POST /ledger/reset`.

### Person 3 — All-in-One Merchant AI Buddy (`services/merchant_agent` | Port `8003`)
> Read `plan.md` and `CONTRACT.md`. You ONLY own `/services/merchant_agent` on Port `8003`. Build the **All-in-One Merchant AI Buddy** seeded with the 6-month historical profile for `PAYTM_MERCH_8821`. On every request (`/merchant/query`, `/merchant/query-audio`, `/merchant/upload-doc`, `/merchant/proactive-shield`):
> 1. Diagnose root cause using historical sales/cashflow context (distinguish payment friction from default).
> 2. Evaluate 3 candidate interventions (`Option A`, `Option B`, `Option C`) and select the best one in `intervention_evaluation`.
> 3. Mint a DPDP consent token and dispatch via A2A to `http://localhost:8002/a2a/dispatch` (with clean fallback if `8002` is offline).
> 4. Log verified outcomes into `strategy_memory` and generate a warm, $\le 35$-word Hinglish voice reply (`8001/llm` + `8001/tts`) combining immediate resolution with a historical business insight. Expose `GET /events` and `POST /reset`.

### Person 4 — 3-Column Command Center UI (`frontend` | Port `3000`)
> Read `plan.md` and `CONTRACT.md`. You ONLY own `/frontend` on Port `3000`. Build a high-contrast 3-column dashboard:
> - **Left Column (Merchant AI Buddy):** Mobile frame with Hindi/Hinglish voice mic + text chat, **6-Month Business Insights Banner** (`₹32k/day avg`, `2.3x Fri–Sun peak`, `Shiprocket & Vyapar Consented`), 1-click demo chips for all 8 scenarios (including Mandate Failed, Growth Advice, Settlement Variance, Fake Screenshot, and Proactive Chargeback Shield), plus PoD/Screenshot upload.
> - **Center Column (Cognitive & A2A Orchestration Trace):** Shows Merchant Buddy's **Intervention Evaluation (`Option A vs B vs C -> Selected`)**, DPDP Consent verification badge, and Paytm's **4 Sub-Agents firing in sequence** (`Intelligence` $\rightarrow$ `Risk` $\rightarrow$ `Resolution` $\rightarrow$ `Ledger Ops`).
> - **Right Column (Paytm Acquiring & Lending Ledger):** Live settlement waterfall, Loan EDI status (`ACTIVE` / `PAUSED 48H` / `UPI LINK SENT`), Chargeback `#9981` (`HELD` $\rightarrow$ `RELEASED`), UTR verification table, and `Verified Outcomes Learned` counter + top-right **Reset Demo** button.

---

## 8. Integration & Demo Walkthrough Sequence

1. **Standalone Verification:** Each teammate runs their service's smoke test (`test_sarvam.py`, `test_paytm.py`, `test_merchant.py`) to confirm `200 OK` across all 8 intents.
2. **4-Port Live Wiring:** Boot `8001`, `8002`, `8003`, and `3000` together on the demo machine and verify `SARVAM_SERVICE_URL` and `PAYTM_AGENT_URL` env vars point to live ports.
3. **3-Act Demo Flow for Judges:**
   * **Act 1 (Root-Cause Mandate Troubleshooting):** Trigger *"Mera ₹500 ka loan EDI mandate fail ho gaya"* $\rightarrow$ Center Panel shows Merchant Buddy diagnosing temporary rain/cash dip (`Friction, not default`), evaluating `Option A (Reminder)` vs. `Option B (UPI Switch / 48h KFS Pause)`, and Paytm's 4 sub-agents resolving it without penalty.
   * **Act 2 (Proactive Chargeback Save):** Trigger incoming chargeback alert `#9981` $\rightarrow$ Merchant Buddy pulls Shiprocket PoD automatically $\rightarrow$ 1-tap Hindi approval $\rightarrow$ `#9981` flips from Amber `HELD` to Emerald `RELEASED`.
   * **Act 3 (Historical Growth & Cashflow Advisory):** Ask *"Mere pichle 6 mahine ke data se business badhane ka suggestion do"* $\rightarrow$ Buddy cites the `2.3x` Friday–Sunday sales surge and recommends a KFS-transparent working capital boost.

---

## Person 3 briefs (received with V3)

**Brief A.** Upgrade `/services/merchant_agent` into an All-in-One Merchant AI Buddy with a rich 6-Month Merchant Historical Dataset (`daily_avg_sales: 32000`, `weekend_multiplier: 2.3x`, `past_edi_success_rate: 96%`, `supplier_payable_tomorrow: 4500`, `recent_customers: [...]`). For every query (`POST /merchant/query`, `/merchant/query-audio`, `/merchant/upload-doc`, or `/merchant/proactive-shield`):
- **Understand Merchant & Diagnose Root Cause:** analyze the query against the merchant's historical data (e.g., distinguish temporary cash dip / mandate friction from willful default).
- **Evaluate Interventions:** generate 2–3 possible actions (e.g., Option A: send reminder, Option B: troubleshoot mandate / pause EDI, Option C: escalate), score them against policy/cost/UX, and pick the best one.
- **A2A Dispatch to Paytm Mesh (8002):** send the chosen intervention + DPDP consent token and capture Paytm's multi-agent `agent_trace`.
- **Verify & Learn + Hindi Buddy Reply:** log the verified outcome into `strategy_memory` so future decisions improve, and reply in warm, insightful Hinglish voice (immediate problem resolution + a smart historical business tip).

**Brief B.**
- Add keyword/LLM routing for 4 new intents: "soundbox wapas / bill kat raha", "loan settle / NOC", "bank account / KYC change", "settlement hold / bank inactive". *(Names chosen in 8003, to be confirmed with Person 2: `SOUNDBOX_RETURN`, `LOAN_CLOSURE_NOC`, `BANK_KYC_UPDATE`, `SETTLEMENT_HOLD_BANK`.)*
- Upgrade `local_gst_itc_log` into a full `khata_bookkeeping_ledger` (`GET /merchant/khata-export`) that aggregates daily sales, bank credits, MDR fees, GST ITC (₹261), and refunds into a downloadable Tally-ready JSON/CSV summary.
