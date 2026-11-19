# Paytm × Sarvam: AI Teammate for Paytm merchants

| Port | Service | Owner |
|---|---|---|
| 8001 | `services/sarvam_service`: Sarvam STT / TTS / LLM / document vision | Person 1 |
| 8002 | `services/paytm_agent`: Paytm's agent mesh + employee console | Person 2 |
| 8003 | `services/merchant_agent`: Merchant AI Buddy (A2A orchestrator) | Person 3 |
| 3000 | `frontend`: merchant app + live decision trace | Person 4 |

Data lives in `data/seed`. Optional persistence is in `supabase/`.

## Run everything with one command
Needs **Python 3.10+** (3.11 preferred) and **Node 20+**.

```bash
cp .env.example .env        # then put your SARVAM_API_KEY in .env (without it Sarvam runs in mock mode)
python run.py               # first run installs everything (~2 min), then starts all four
```
Open **http://localhost:3000**. The Paytm employee console is at http://localhost:8002/. Logs from all four are
shown together, labelled per service. **Ctrl+C stops everything and frees the ports.**

| Command | What it does |
|---|---|
| `python run.py` | Dev: 8001 + 8002 + 8003 + frontend on 3000, with frontend hot-reload |
| `python run.py prod` | Everything on **one port** (http://localhost:8080), exactly like the deployment |
| `python run.py test` | All test suites (Sarvam, Paytm, Merchant) + a frontend production build |
| `python run.py smoke` | Starts the one-port stack, plays the demo through it (settlement, fake screenshot, cashflow → EDI pause, khata, console), then stops it. Sarvam runs in mock mode; add `--live` to use your key |
| `python run.py eval` | Short live eval: 23 Hindi/English questions scored on intent, right fact and right language (needs the Sarvam key) |
| `python run.py stop` | Frees ports 3000, 8001–8003, 8080 if something was left running |
| `python run.py setup` | Reinstall dependencies (done automatically when the requirements change) |

## Manual test (5 minutes)
1. `python run.py`, then open http://localhost:3000. The header should say **Live services**.
2. Press **▶ Play guided demo**: settlement → chargeback PoD → fake screenshot → cashflow alert.
3. Tap **"हाँ, EDI 2 दिन रोक दो"**. The ledger on the right should show Loan EDI **PAUSED** and chargeback #9981 **RELEASED**.
4. Open **खाता**: GST ITC ₹261 logged, reconciled, with a Tally CSV export.
5. Press **Reset** before the next run.

## If voice doesn't work
- Header says **"Voice off: Sarvam key missing"**, or `run.py` prints **MOCK**: put `SARVAM_API_KEY` in `.env` and restart.
  Without it the app still works through the preset buttons and the **"या यहाँ लिखिए…"** box.
- The buddy only answers questions about this merchant's Paytm business. Anything else, or speech it couldn't make
  out, gets a polite "please rephrase" instead of a guessed answer.
- `REPLY_LLM=1` in `.env` lets Sarvam's LLM phrase the replies (default: tested templates, which are exact and faster).

## Deploy
One Railway service from the root `Dockerfile`, no Vercel needed. See [deploy/README.md](deploy/README.md).
