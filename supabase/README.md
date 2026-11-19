# Supabase: persistent state for the A2A demo

Both datasets live in Postgres (project `paytm-a2a-hackathon`, ref `ijitntwpnqwkjrboweky`, Mumbai).
The agents read and write real tables, the console can follow the ledger live through Realtime,
and **Reset Demo** restores the exact start state in ~40 ms.
Nothing in `CONTRACT.md` changes: the database sits behind the same endpoints.

```
merchant_agent (8003) ──A2A HTTP──▶ paytm_agent (8002)        frontend (3000)
      │ merchant_svc role                 │ paytm_svc role          │ anon key (read-only)
      ▼                                   ▼                         ▼
 schema `merchant`  ◀── no grants ──▶  schema `paytm`   ──Realtime──▶ useLedgerRealtime()
```

* **Two schemas, two roles.** `merchant_svc` has no privileges on `paytm` and vice versa, so the
  boundary is enforced by Postgres, not by convention. The agents only talk over A2A HTTP.
* **RLS on every table**, deny by default. `anon` can only `SELECT` 8 live tables, scoped to
  `mid = 'PAYTM_MERCH_8821'`. The service-role key is never used by the services or the frontend.
* **Atomic changes are Postgres functions.** Releasing a chargeback, pausing an EDI, executing a
  refund and switching a bounced mandate to a UPI link each run as one transaction.
* **Write-through with fallback.** The in-memory state stays the hot copy that responses are built
  from. Each change is mirrored by the function call. With `USE_SUPABASE=false` (the default), or if
  Supabase is unreachable, the services log one line and run on memory alone (30 s circuit breaker).

## Folder

| Path | What |
|---|---|
| `migrations/001–011` | Schemas, roles, enums, tables, grants + RLS, functions, Realtime, fixes. **Already applied** to the project. |
| `seed/load_seed.py` | Loads `data/seed` + `data/paytm` (40,609 rows, ~1 s), snapshots, resets, verifies against `ledger_initial_state.json`. Idempotent. |
| `tests/test_supabase_db.py` | Role boundary + RLS, consent logging, all 8 intents + guardrails, then reset = byte-identical start state in < 2 s. |
| `frontend/useLedgerRealtime.js` | React hook for Person 4: initial fetch + live updates, anon key only. |
| `../services/paytm_agent/app/repository.py` | Person 2's data-access module (+ 3 small hooks: `dispatch.py`, `proactive.py`, `store.py`). |
| `../services/merchant_agent/repository.py` | Person 3's data-access module (+ hooks in `state.py`, one line each in `advisor.py`, `pipeline.py`). |

## One-time setup (≈5 minutes, on your laptop)

**Quick path (one command).** After step 2 below (expose the schemas), run from the repo root:
```bash
python -m pip install "psycopg[binary]" psycopg-pool pandas pytest
python supabase/seed/setup_local.py
```
It asks for the database password once (hidden; Project Settings → Database → Reset if forgotten), loads and verifies
the data, gives `paytm_svc` / `merchant_svc` fresh random passwords (sent as SCRAM hashes, never printed) and writes
`USE_SUPABASE=true` + the connection strings into the services' git-ignored `.env` files. Steps 1, 3 and 4 below are
what it does, if you prefer to do them by hand.


1. **Give the service roles passwords**: Dashboard → SQL Editor. Use two new random strings; never commit them:
   ```sql
   alter role paytm_svc    with password '<random-1>';
   alter role merchant_svc with password '<random-2>';
   ```
2. **Expose the schemas for the frontend**: Dashboard → Project Settings → Data API → *Exposed schemas* → add `paytm`, `merchant`.
   (RLS still limits `anon` to read-only on 8 tables.)
3. **Load the data** with the owner connection: Dashboard → **Connect** → *Session pooler* string, with your DB password:
   ```bash
   pip install "psycopg[binary]" psycopg-pool pandas pytest
   cp supabase/.env.example supabase/.env           # fill SUPABASE_DB_URL (git-ignored)
   set -a; source supabase/.env; set +a
   python supabase/seed/load_seed.py                # -> "VERIFY OK: database matches ..."
   python -m pytest supabase/tests -q               # -> 3 passed
   ```
4. **Turn it on in the services**: add to `services/paytm_agent/.env` and `services/merchant_agent/.env`
   (transaction pooler, port 6543; the user name is `<role>.<project-ref>`):
   ```
   USE_SUPABASE=true
   PAYTM_DB_URL=postgresql://paytm_svc.ijitntwpnqwkjrboweky:<random-1>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   MERCHANT_DB_URL=postgresql://merchant_svc.ijitntwpnqwkjrboweky:<random-2>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   ```
   (Copy the exact pooler host from Dashboard → Connect; it can differ from `aws-0-…`.)
5. **Smoke-test both services against Supabase**:
   ```bash
   cd services/paytm_agent    && python -m pytest tests/test_supabase_mode.py tests/test_supabase_fallback.py -q
   cd services/merchant_agent && python -m pytest test_supabase_mode.py -q
   ```
6. **Frontend (Person 4)**: `npm i @supabase/supabase-js`, copy `supabase/frontend/useLedgerRealtime.js` into
   `frontend/src/`, and set `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` (Dashboard → Project Settings → API)
   in `frontend/.env`. After calling `/reset`, call `live.refetch()`: Realtime does not stream `TRUNCATE`.

## What each agent writes

| Scenario | paytm_agent → `paytm` | merchant_agent → `merchant` |
|---|---|---|
| every call | `consent_checks` (incl. refused), `agent_trace`, `verified_outcomes`, `demo_counters` | `a2a_events` (every step, live feed) |
| CHARGEBACK_RESOLVE | `release_chargeback()`: status RELEASED + history + `pending_credits` | |
| UTR_VERIFY | `verify_utr()` → `utr_checks`; a fake UTR also writes `fraud_signals` | `fraud_alerts` |
| DUPLICATE_RECONCILE | `execute_refund()` (idempotent, never more than paid) | |
| CASHFLOW_EDI_SWITCH | `pause_edi()`: `loan_book` + `lender_approvals` + `kfs_consent_artifacts` | `agent_state.loan_edi_status` |
| ESCALATE_HUMAN | `create_l2_ticket()` → `tickets` (TKT-PAYTM-1291…, `diagnostics.service_ticket_id` links the service's own id) | |
| SETTLEMENT_RECONCILE | read-only | `gst_itc_log` (idempotent) |
| outcomes | | `strategy_memory` (learned rows; 8 seeded rows survive reset) |

Functions raise `CODE: detail`; the services map them to the contract's errors:
`CONSENT_INVALID` → 403 `DPDP_CONSENT_REQUIRED`, `EDI_PAUSE_NOT_ELIGIBLE` → 409.
Database-level guardrails hold even against a direct `UPDATE`: a refund above ₹5,000 can't be `PROCESSED`
without a human approver (a table constraint), and the KFS 4.2 limit is max 2 days, DPD 0, ≥ 90 % first-attempt success.

## Reset

`POST :8002/ledger/reset` and `POST :8003/reset` call `paytm.reset_demo()` / `merchant.reset_demo()`:
audit tables truncated, live rows removed, `refunds`, `chargebacks`, `loan_book` and `enach_mandates` restored
column-for-column from the snapshot taken by the loader, counters and id sequences rewound (next ticket
`TKT-PAYTM-1291`), and the CB-9981 evidence deadline moved to now + 48 h. Re-run `load_seed.py` to rebuild everything.

## Known gaps

* **paytm_agent's in-memory seed still differs from `data/paytm`** (duplicate order 4455/₹3,200 vs 4489/₹1,180,
  bounce date 19 vs 17 Nov, bounce charge ₹118 vs 0). Until `app/seed.py` is aligned, the duplicate refund is
  logged as "DB diverged" instead of written (`test_duplicate_refund_is_written` is marked xfail).
* The service's own ₹2,000 discretionary-refund limit stays in code; the database only enforces the ₹5,000 backstop.
* merchant-side khata entries, dispute packets and EDI offers are mirrored as `a2a_events` payloads, not as rows.
* Free-tier projects pause after a week without traffic: restore from the dashboard before the demo.
