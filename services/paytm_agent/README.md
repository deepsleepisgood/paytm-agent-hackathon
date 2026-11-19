# Paytm AI Teammate — Person 2 (port 8002)

The service that owns the merchant's ledger, decides what may be done without a human,
takes the actions it is allowed to take, and records every call. It also serves the
employee console, so there is one thing to deploy and one live link.

**The user of this product is a Paytm support employee**, not the merchant. The merchant
talks to Person 3; we answer Person 3 and we prepare cases for the humans.

## Run it

```bash
cd services/paytm_agent
./run.sh                      # creates .venv, installs, serves on 8002
```

Then open **http://localhost:8002/** for the employee console.

```bash
pytest -q                     # 254 tests, no network, no key
BASE=http://127.0.0.1:8002 ./scripts/demo.sh   # 82 live checks against a running server
```

`demo.sh` refuses to run against a server on old code, which otherwise costs ten
confusing minutes when routes you just wrote appear to "fail".

Deploy with the Dockerfile, **built from the repo root** so the dataset comes along:

```bash
docker build -f services/paytm_agent/Dockerfile -t paytm-agent .
docker run -p 8002:8002 -e ALLOWED_ORIGINS=https://your-frontend paytm-agent
```

`PORT` and `ALLOWED_ORIGINS` (or `CORS_ORIGINS`, as sarvam_service names it — both work)
come from the environment. Nothing is pinned to localhost.

## The one rule

**No language model runs in this service.** Every rupee figure is read from the ledger by
Python. `template_text` is string formatting. The model (Person 1's) picks the intent and
words the reply; it never does arithmetic. A chatbot that tells a shopkeeper ₹4,160 when
the answer is ₹4,610 is worse than no product.

## Four sub-agents

Every request is worked by the same four, in order, and each reports what it did. That
report is returned as `agent_trace` and shown in the console.

| Sub-agent | Job |
|---|---|
| `IntelligenceAgent` | Reads. Parses the request and pulls the relevant facts. Decides nothing. |
| `RiskPolicyAgent` | Judges. Applies the policy constants: close it, or hand it to a human. |
| `ResolutionAgent` | Composes. The remedy, and the sentence the merchant hears. |
| `LedgerOpsAgent` | Acts. The only one allowed to change the merchant's account. |

The split is not decoration. It answers two awkward questions directly: *could your AI
have moved my money?* — look at whether `LedgerOpsAgent` acted — and *why was this
escalated?* — `RiskPolicyAgent`'s line, and nothing else decides. A sub-agent with
nothing to do still reports in, because "no ledger change required" is evidence.

Adding an intent is four small functions in `app/intents/<name>.py` (`gather`, `assess`,
`resolve`, `apply`), each returning one line for the trace. Omit a stage and it reports
itself idle.

## Endpoints

| | |
|---|---|
| `POST /a2a/dispatch` | The one entry point Person 3 calls |
| `POST /a2a/proactive-alert` | Paytm speaks first (V2 delta). **No consent token:** it only informs |
| `POST /a2a/execute-edi-pause` | Pause the NBFC's daily instalment. 403 without consent, 409 outside KFS 4.2 |
| `GET /ledger/{mid}` | Full live state |
| `POST /ledger/reset` | `?chargeback_hours_left=N` and `?break_settlement=1` are the demo levers |
| `GET /summaries`, `GET /summaries/{id}` | Call feed; one row opens to its `agent_trace` |
| `GET /tickets`, `POST /tickets/{id}/claim`, `.../resolve` | The queue a human works |
| `GET /metrics` | The numbers strip |
| `GET /health`, `GET /` | Liveness, and the console |

Ten intents are handled: the eight scenarios plus `FEE_GST_LOAN` and `REFUND_MANAGE`,
which sarvam_service still routes to.

## For Persons 1, 3 and 4

- **Both spellings work.** `DUPLICATE_RECONCILE` and `GROWTH_ADVISORY` resolve to
  `DUPLICATE_PAYMENT_RECONCILE` and `WORKING_CAPITAL_ADVISORY`. The response echoes the
  name you sent, and adds `intent_canonical` when they differ.
- **Field names are forgiving** where the specs disagree: `utr` or `utr_number`,
  `claimed_amount_inr` or `amount`, `amount_inr` or `amount` on a document, and the
  chargeback payload in either the V2-delta or the richer form.
- **A missing `reason_code` on `ESCALATE_HUMAN`** defaults to `MERCHANT_REQUESTED_HUMAN`
  rather than erroring.
- **Every failure uses one shape:** `{"error": {"code", "message", "retryable"}}`, including
  malformed bodies. You branch on `code`, never on the message.
- **`/a2a/dispatch` is idempotent on `request_id`.** A replay returns the original
  response and writes no second summary, ticket or ledger change.
- **Our error envelope has no `status` key.** `upstream.py` treats that as "8002 is
  unavailable" and silently falls back to its mock — so a 4xx from us looks like the
  service being down. Worth logging the body when that happens.

## Things decided on purpose

- **An unknown payment reference is "not in your account", never "fake."** The internal
  `POSSIBLE_FAKE` flag exists in `data` because the contract asks for it, and never
  reaches `template_text`, a summary or a ticket. A database miss cannot support an
  accusation, and the merchant is the one who would repeat it to their customer's face.
  A test checks every merchant-facing string on every branch.
- **The agent will not advise borrowing.** `WORKING_CAPITAL_ADVISORY` gives the merchant
  their own numbers and the real cost of the loan they have; "should I take it?"
  escalates. No rate or tenure is invented — those belong in the KFS.
- **Chargeback checks run deadline → confidence → fields.** All three can be true at
  once; the deadline wins because it is the only one a phone call can still fix.
- **`simulated: true` on a released hold**, and said out loud: the banks decide a dispute,
  not this agent.
- **A settlement that has closed is never rewritten.** Refunds issued today are marked as
  today's, so the five lines still add to ₹4,160.
- **Proactive alerts are not merchant calls** and stay out of `calls_total`, so the
  auto-resolution rate means what it says.

## Data

Figures come from the team's canonical dataset. `tests/test_canonical_alignment.py`
compares our seed to `data/paytm/ledger_initial_state.json` field by field and fails when
they drift — it exists because they drifted three times in one afternoon, each caught
only by someone happening to read the file.

UTR lookups read `data/paytm/npci_utr_log.csv` (6,535 payments). `PAYTM_DATA_DIR`
overrides the location. Without the file the seeded references still work, but nearly
every real reference would answer "I cannot find this payment", which also tells the
merchant to withhold goods — the worst direction to be confidently wrong in.

## Known, and deliberate

- **State is in memory and dies on restart.** Fine for a rehearsed demo; it means the
  queue and the numbers reset. All of it lives in `app/store.py` and nowhere else, so
  moving it to a database is one module.
- **The EDI question is unsettled.** The canonical loan data says the ₹500 is collected
  by eNACH from the bank account, not netted from settlements; the contract's
  `projected_net_payout: 1200` subtracts it from the payout. We follow the contract,
  because Person 1's recorded reply and Person 3's code both depend on 1,200, and carry
  `edi_collection_method` beside the number rather than hiding the discrepancy.
  **Worth settling.**
- **Three divergences from the dataset** are recorded as assertions in
  `test_canonical_alignment.py` with reasons: we never use the `NOT_FOUND_SUSPECTED_FAKE`
  label, the chargeback deadline stays relative so acceptance case 6 works, and ticket ids
  follow the contract's `tkt_001` rather than the dataset's `TKT-PAYTM-1291`.

## Files

```
app/main.py         app factory, CORS, console, error shape
app/dispatch.py     the envelope: validation, idempotency gate, side-effect order
app/mesh.py         the four sub-agents and the trace
app/intents/        one module per intent, four small functions each
app/seed.py         the ledger: one source of every rupee figure
app/store.py        all mutable state, in one place
app/escalation.py   reason codes, tickets, what the employee is told to do next
app/templates.py    what the merchant hears, and the banned-word rule
app/metrics.py      the numbers strip, derived from the records
app/dataset.py      loads the canonical UTR log when it is there
app/static/         the employee console, no build step
```
