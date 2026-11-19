#!/usr/bin/env bash
# Every stage's check as a curl you can read, in order.
#
#   ./scripts/demo.sh                 # against http://127.0.0.1:8002
#   BASE=http://127.0.0.1:8102 ./scripts/demo.sh
#
# pytest proves the service is correct; this script is for showing someone that it is.
set -uo pipefail

BASE="${BASE:-http://127.0.0.1:8002}"
MID="${MID:-PAYTM_MERCH_8821}"

pass=0; fail=0
say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
check() { # check <label> <actual> <expected>
  if [ "$2" = "$3" ]; then printf '  \033[32mPASS\033[0m %s = %s\n' "$1" "$2"; pass=$((pass+1))
  else printf '  \033[31mFAIL\033[0m %s = %s (expected %s)\n' "$1" "$2" "$3"; fail=$((fail+1)); fi
}

# Guard against the trap that costs ten confusing minutes: an old uvicorn still holding
# the port, so the routes you just wrote appear to "fail" when they were never deployed.
EXPECTED_ROUTES='/a2a/dispatch /a2a/proactive-alert /a2a/execute-edi-pause /ledger/{mid} /summaries /tickets /metrics'
LIVE_ROUTES=$(curl -s --max-time 5 "$BASE/openapi.json" | jq -r '.paths | keys[]' 2>/dev/null)
if [ -z "$LIVE_ROUTES" ]; then
  printf '\033[31mNo service answering at %s\033[0m\n' "$BASE"; exit 1
fi
for route in $EXPECTED_ROUTES; do
  if ! grep -qxF "$route" <<< "$LIVE_ROUTES"; then
    printf '\033[31mThe server at %s is running OLD code: %s is missing.\033[0m\n' "$BASE" "$route"
    printf 'Restart it:  pkill -f "uvicorn app.main:app" && .venv/bin/python -m uvicorn app.main:app --port %s\n' "${BASE##*:}"
    exit 1
  fi
done

say "Stage 0 — the service is up"
check "health"        "$(curl -s "$BASE/health" | jq -c .)" '{"ok":true,"service":"paytm_agent"}'
check "console type"  "$(curl -s -o /dev/null -w '%{content_type}' "$BASE/")" 'text/html; charset=utf-8'

say "Stage 1 — the ledger adds up"
curl -s -X POST "$BASE/ledger/reset" > /dev/null
L=$(curl -s "$BASE/ledger/$MID")
check "deductions add to the gap" \
      "$(echo "$L" | jq '[.settlement.lines[].amount_inr] | add')" "4160"
check "gap is gross minus net" \
      "$(echo "$L" | jq '.settlement.gross_inr - .settlement.net_credit_inr')" "4160"
check "reconciles"    "$(echo "$L" | jq -c '.settlement.reconciles')" "true"
check "MDR bands add to the fee line" \
      "$(echo "$L" | jq '[.mdr_breakdown[].fee_inr] | add')" "1450"
check "GST is 18% of the fee" \
      "$(echo "$L" | jq '.settlement.lines[] | select(.code=="GST_ON_MDR") | .amount_inr')" "261"
check "loan EDI"      "$(echo "$L" | jq '.loan.edi_per_day_inr')" "500"
check "chargeback held" "$(echo "$L" | jq -r '.chargeback.hold_status')" "HELD"

say "Stage 1 — the demo levers work"
curl -s -X POST "$BASE/ledger/reset?break_settlement=true" > /dev/null
check "broken ledger stops reconciling" \
      "$(curl -s "$BASE/ledger/$MID" | jq -c '.settlement.reconciles')" "false"
check "default deadline is not urgent (> 12h)" \
      "$(curl -s "$BASE/ledger/$MID" | jq -c '.chargeback.hours_left > 12')" "true"
curl -s -X POST "$BASE/ledger/reset?chargeback_hours_left=6" > /dev/null
check "urgent deadline lever (< 12h)" \
      "$(curl -s "$BASE/ledger/$MID" | jq -c '.chargeback.hours_left < 12')" "true"
curl -s -X POST "$BASE/ledger/reset" > /dev/null
check "unknown merchant is UNKNOWN_MID" \
      "$(curl -s "$BASE/ledger/NOPE" | jq -r '.error.code')" "UNKNOWN_MID"

say "Stage 2 — one call, one record, even when replayed"
curl -s -X POST "$BASE/ledger/reset" > /dev/null
REQ='{"request_id":"demo-1","session_id":"s-1","mid":"'"$MID"'","intent":"ESCALATE_HUMAN",
      "language_code":"hi-IN","merchant_said":"mujhe kisi insaan se baat karni hai",
      "payload":{"reason_code":"MERCHANT_REQUESTED_HUMAN","tried":["Explained settlement"]},
      "consent_token":"ct-abc"}'
A=$(curl -s -X POST "$BASE/a2a/dispatch" -H 'content-type: application/json' -d "$REQ")
B=$(curl -s -X POST "$BASE/a2a/dispatch" -H 'content-type: application/json' -d "$REQ")

check "escalates"           "$(echo "$A" | jq -r '.status')" "ESCALATED"
check "replay is identical" "$( [ "$A" = "$B" ] && echo same || echo different )" "same"
check "one summary, not two" "$(curl -s "$BASE/summaries" | jq '.summaries | length')" "1"
check "one ticket, not two"  "$(curl -s "$BASE/tickets"   | jq '.tickets | length')"   "1"
check "summary links to its ticket" \
      "$(curl -s "$BASE/summaries" | jq -r '.summaries[0].ticket_id')" \
      "$(echo "$A" | jq -r '.escalation_ticket.ticket_id')"

say "Stage 2 — the employee works the queue"
TID=$(echo "$A" | jq -r '.escalation_ticket.ticket_id')
check "claim"          "$(curl -s -X POST "$BASE/tickets/$TID/claim" -H 'content-type: application/json' -d '{"employee":"Asha"}' | jq -r '.status')" "CLAIMED"
check "no double claim" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/tickets/$TID/claim" -H 'content-type: application/json' -d '{"employee":"Bhavna"}')" "409"
check "resolve"        "$(curl -s -X POST "$BASE/tickets/$TID/resolve" -H 'content-type: application/json' -d '{"employee":"Asha","note":"Called the merchant"}' | jq -r '.status')" "RESOLVED"

say "Stage 2 — every failure uses the contract error shape"
for pair in 'CONSENT_MISSING:"consent_token":""' 'UNKNOWN_MID:"mid":"NOPE"' 'UNKNOWN_INTENT:"intent":"MAKE_TEA"'; do
  code="${pair%%:*}"; override="${pair#*:}"
  got=$(curl -s -X POST "$BASE/a2a/dispatch" -H 'content-type: application/json' \
        -d "{\"request_id\":\"e-$code\",\"mid\":\"$MID\",\"intent\":\"ESCALATE_HUMAN\",\"consent_token\":\"ct\",\"payload\":{\"reason_code\":\"MERCHANT_REQUESTED_HUMAN\"},$override}" \
        | jq -r '.error.code')
  check "$code" "$got" "$code"
done
check "rejected calls write no feed row" \
      "$(curl -s "$BASE/summaries" | jq '.summaries | length')" "1"

say "Stage 3 — the numbers strip reads from the record"
curl -s -X POST "$BASE/ledger/reset" > /dev/null
M=$(curl -s "$BASE/metrics")
check "cold start: no calls"      "$(echo "$M" | jq '.calls_total')" "0"
check "cold start: rate is 0, not an error" "$(echo "$M" | jq -c '.auto_resolution_rate == 0')" "true"
check "cold start: AI average is null, not 0"    "$(echo "$M" | jq -c '.avg_resolution_ms_ai')" "null"
check "cold start: human average is null, not 0" "$(echo "$M" | jq -c '.avg_resolution_ms_human')" "null"
check "nothing renders as NaN"    "$(echo "$M" | grep -ci 'nan')" "0"

curl -s -X POST "$BASE/a2a/dispatch" -H 'content-type: application/json' -d "$REQ" > /dev/null
M=$(curl -s "$BASE/metrics")
check "one call recorded"  "$(echo "$M" | jq '.calls_total')" "1"
check "counted as escalated" "$(echo "$M" | jq '.escalated')" "1"
check "one ticket waiting"   "$(echo "$M" | jq '.tickets_open')" "1"
check "outcomes account for every call" \
      "$(echo "$M" | jq '.resolved_by_ai + .escalated + .awaiting_merchant == .calls_total')" "true"

for _ in 1 2 3; do curl -s -X POST "$BASE/a2a/dispatch" -H 'content-type: application/json' -d "$REQ" > /dev/null; done
check "replays cannot inflate the numbers" \
      "$(curl -s "$BASE/metrics" | jq '.calls_total')" "1"

say "Stage 4 — the call this product exists to answer"
curl -s -X POST "$BASE/ledger/reset" > /dev/null
SETTLE='{"request_id":"s-1","session_id":"demo","mid":"'"$MID"'","intent":"SETTLEMENT_RECONCILE",
         "language_code":"hi-IN","merchant_said":"mujhe 95,840 hi kyun mile?",
         "payload":{},"consent_token":"ct-abc"}'
S=$(curl -s -X POST "$BASE/a2a/dispatch" -H 'content-type: application/json' -d "$SETTLE")

check "resolved with no human"  "$(echo "$S" | jq -r '.status')" "RESOLVED"
check "no ticket raised"        "$(echo "$S" | jq -c '.escalation_ticket')" "null"
check "five lines"              "$(echo "$S" | jq '.data.lines | length')" "5"
check "lines explain the gap"   "$(echo "$S" | jq -c '.data | ([.lines[].amount_inr] | add) == .variance_inr')" "true"
check "tomorrow's loan flagged" "$(echo "$S" | jq '.data.upcoming[0].amount_inr')" "500"
check "nothing accusatory said" "$(echo "$S" | jq -r '.template_text' | grep -ciE 'fake|fraud|scam|suspicious')" "0"
check "counted as deflected"    "$(curl -s "$BASE/metrics" | jq '.resolved_by_ai')" "1"

printf '\n  \033[2mwhat the merchant hears:\033[0m\n'
echo "$S" | jq -r '.template_text' | fold -s -w 72 | sed 's/^/    /'

say "Stage 4 — an unexplained gap is not recited as if it were explained"
curl -s -X POST "$BASE/ledger/reset?break_settlement=true" > /dev/null
B=$(curl -s -X POST "$BASE/a2a/dispatch" -H 'content-type: application/json' -d "$SETTLE")
check "escalates instead"  "$(echo "$B" | jq -r '.status')" "ESCALATED"
check "with the right reason" "$(echo "$B" | jq -r '.escalation_ticket.reason_code')" "SETTLEMENT_UNRECONCILED"
check "breakdown still travels with the ticket" "$(echo "$B" | jq '.data.lines | length')" "5"
printf '\n  \033[2mwhat the merchant hears instead:\033[0m\n'
echo "$B" | jq -r '.template_text' | fold -s -w 72 | sed 's/^/    /'
curl -s -X POST "$BASE/ledger/reset" > /dev/null

say "Stage 5 — Paytm speaks first, and pauses the loan when told to"
curl -s -XPOST "$BASE/ledger/reset" > /dev/null
AL=$(curl -s -XPOST "$BASE/a2a/proactive-alert" -H 'content-type: application/json' \
     -d '{"mid":"'"$MID"'","trigger_type":"HIGH_REFUND_CASHFLOW"}')
check "alert raised"              "$(echo "$AL" | jq -r '.status')" "ALERT_RAISED"
check "no consent needed to warn" "$(echo "$AL" | jq -r '.alert_id')" "ALERT-4490"
check "payout projected short"    "$(echo "$AL" | jq '.data.projected_net_payout')" "1200"
check "pause offered under KFS"   "$(echo "$AL" | jq -r '.data.edi_pause_offer.kfs_clause')" "4.2"

OID=$(echo "$AL" | jq -r '.data.edi_pause_offer.offer_id')
check "pause without consent is 403" \
      "$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$BASE/a2a/execute-edi-pause" \
         -H 'content-type: application/json' -d '{"mid":"'"$MID"'","offer_id":"'"$OID"'"}')" "403"
check "three days breaks KFS 4.2 (409)" \
      "$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$BASE/a2a/execute-edi-pause" \
         -H 'content-type: application/json' -d '{"mid":"'"$MID"'","consent_token":"ct","pause_days":3,"offer_id":"'"$OID"'"}')" "409"
P=$(curl -s -XPOST "$BASE/a2a/execute-edi-pause" -H 'content-type: application/json' \
    -d '{"mid":"'"$MID"'","consent_token":"DPDP_VERIFIED_TS_1763","pause_days":2,"offer_id":"'"$OID"'"}')
check "pause executed"      "$(echo "$P" | jq -r '.status')" "EDI_PAUSED"
check "resumes 21 November" "$(echo "$P" | jq -r '.data.resume_date')" "2026-11-21"
check "payout now better"   "$(curl -s "$BASE/ledger/$MID" | jq '.projected_net_payout_inr')" "1700"
check "pausing twice is 409" \
      "$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$BASE/a2a/execute-edi-pause" \
         -H 'content-type: application/json' -d '{"mid":"'"$MID"'","consent_token":"ct","offer_id":"'"$OID"'"}')" "409"
check "alerts stay out of the call feed" \
      "$(curl -s "$BASE/summaries" | jq '.summaries | length')" "0"

say "Stage 6 — four sub-agents, and a trace of what each one did"
curl -s -XPOST "$BASE/ledger/reset" > /dev/null
T=$(curl -s -XPOST "$BASE/a2a/dispatch" -H 'content-type: application/json' -d "$SETTLE")
check "all four reported"   "$(echo "$T" | jq '.agent_trace | length')" "4"
check "in order"            "$(echo "$T" | jq -r '[.agent_trace[].agent] | join(",")')" \
                            "IntelligenceAgent,RiskPolicyAgent,ResolutionAgent,LedgerOpsAgent"
check "nothing was changed" "$(echo "$T" | jq -c '.agent_trace[3].acted')" "false"
printf '\n  \033[2mwho did what:\033[0m\n'
echo "$T" | jq -r '.agent_trace[] | "    \(.step). \(.agent)\(if .acted then "" else " [idle]" end): \(.note)"' | fold -s -w 96

curl -s -XPOST "$BASE/ledger/reset?break_settlement=true" > /dev/null
T2=$(curl -s -XPOST "$BASE/a2a/dispatch" -H 'content-type: application/json' -d "$SETTLE")
check "same read, different verdict" \
      "$( [ "$(echo "$T" | jq -r '.agent_trace[0].note')" = "$(echo "$T2" | jq -r '.agent_trace[0].note')" ] \
          && [ "$(echo "$T" | jq -r '.agent_trace[1].note')" != "$(echo "$T2" | jq -r '.agent_trace[1].note')" ] \
          && echo yes || echo no )" "yes"
curl -s -XPOST "$BASE/ledger/reset" > /dev/null

say "Stage 7 — \"did this payment actually arrive?\""
curl -s -XPOST "$BASE/ledger/reset" > /dev/null
utr () { # utr <request_id> <session_id> <utr>
  curl -s -XPOST "$BASE/a2a/dispatch" -H 'content-type: application/json' \
    -d "{\"request_id\":\"$1\",\"session_id\":\"$2\",\"mid\":\"$MID\",\"intent\":\"UTR_VERIFY\",
         \"language_code\":\"hi-IN\",\"merchant_said\":\"payment aaya kya?\",
         \"payload\":{\"utr\":\"$3\"},\"consent_token\":\"ct\"}"
}

OK=$(utr q1 shop-1 632184920111)
PN=$(utr q2 shop-2 632184920999)
NF=$(utr q3 shop-3 111111111111)
check "settled -> release goods"     "$(echo "$OK" | jq -r '.data.advice')" "RELEASE_GOODS"
check "pending -> wait"              "$(echo "$PN" | jq -r '.data.advice')" "WAIT"
check "unknown -> hold the goods"    "$(echo "$NF" | jq -r '.data.advice')" "DO_NOT_RELEASE_YET"
check "unknown is flagged internally" "$(echo "$NF" | jq -r '.data.internal_flag')" "POSSIBLE_FAKE"
check "but the flag is never spoken"  "$(echo "$NF" | jq -r '.template_text' | grep -ci 'POSSIBLE_FAKE')" "0"
for v in OK PN NF; do
  eval "R=\$$v"
  check "nothing accusatory ($v)" \
        "$(echo "$R" | jq -r '.template_text' | grep -ciE 'fake|fraud|scam|suspicious')" "0"
done
printf '\n  \033[2mwhat the shopkeeper hears when it is not there:\033[0m\n'
echo "$NF" | jq -r '.template_text' | fold -s -w 72 | sed 's/^/    /'

utr p1 shop-x 111111111111 > /dev/null
utr p2 shop-x 222222222222 > /dev/null
TH=$(utr p3 shop-x 333333333333)
check "three unknowns in one chat escalates" "$(echo "$TH" | jq -r '.status')" "ESCALATED"
check "for the right reason" "$(echo "$TH" | jq -r '.escalation_ticket.reason_code')" "REPEATED_UNKNOWN_UTR"
check "fraud flags counted"  "$(curl -s "$BASE/metrics" | jq '.fraud_flags')" "4"

say "All ten intents answer, under either team's spelling"
for pair in 'DUPLICATE_RECONCILE:200' 'GROWTH_ADVISORY:200' 'MANDATE_TROUBLESHOOT:200' \
            'SETTLEMENT_RECONCILE:200' 'CHARGEBACK_RESOLVE:200' 'CASHFLOW_EDI_SWITCH:200' \
            'WORKING_CAPITAL_ADVISORY:200' 'DUPLICATE_PAYMENT_RECONCILE:200' \
            'FEE_GST_LOAN:200' 'ESCALATE_HUMAN:200' 'MAKE_TEA:400'; do
  name="${pair%%:*}"; want="${pair#*:}"
  got=$(curl -s -o /dev/null -w '%{http_code}' -XPOST "$BASE/a2a/dispatch" \
        -H 'content-type: application/json' \
        -d "{\"request_id\":\"n-$name\",\"mid\":\"$MID\",\"intent\":\"$name\",\"consent_token\":\"ct\",\"payload\":{}}")
  check "$name" "$got" "$want"
done

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
