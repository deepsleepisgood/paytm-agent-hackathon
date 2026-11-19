"""Does our seed still agree with the team's canonical Paytm-side dataset?

`data/paytm/ledger_initial_state.json` is the authoritative starting state for this
service. Our seed holds the same figures in Python, which is faster to work with and
keeps the service runnable on its own, but it means there are two copies of every
number — and two copies drift.

They already drifted three times in one afternoon. Before the dataset existed, this
service invented an MDR split (45,000 / 50,000 / 5,000) that totalled correctly and was
wrong, a duplicate on order 4455 when the real one is 4489, and a pre-approved facility
that does not exist. All three were caught by a person happening to read the dataset.

So this file is the automatic version of that reading. It fails the moment the two
disagree, which turns silent drift into a red test. It asserts nothing about behaviour;
every other test file does that.

If it fails, the dataset is right and our seed is wrong — unless the mismatch is one of
the deliberate divergences recorded at the bottom, in which case add to those and say
why.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import seed

# services/paytm_agent/tests/ -> repo root
CANONICAL = Path(__file__).resolve().parents[3] / "data" / "paytm" / "ledger_initial_state.json"

pytestmark = pytest.mark.skipif(
    not CANONICAL.exists(),
    reason="data/paytm/ledger_initial_state.json not present (service checked out alone)",
)


@pytest.fixture(scope="module")
def canonical() -> dict:
    return json.loads(CANONICAL.read_text())


@pytest.fixture(scope="module")
def ledger():
    return seed.fresh()


def test_the_merchant_is_the_same_one(canonical, ledger):
    assert ledger.mid == canonical["mid"]


def test_settlement_totals_match(canonical, ledger):
    s = canonical["settlement"]
    assert ledger.settlement_date == s["settlement_date"]
    assert ledger.gross_inr == s["gross"]
    assert ledger.net_credit_inr == s["net_credit"]
    assert ledger.variance_inr == s["variance"]


def test_every_deduction_matches(canonical, ledger):
    d = canonical["settlement"]["deductions"]
    ours = {line["code"]: line["amount_inr"] for line in ledger.lines}

    assert ours["MDR_FEE"] == d["mdr"]
    assert ours["GST_ON_MDR"] == d["gst_on_mdr"]
    assert ours["CUSTOMER_REFUND"] == d["refund_4412"]
    assert ours["SOUNDBOX_RENTAL"] == d["soundbox_rental"]
    assert ours["CHARGEBACK_HOLD"] == d["chargeback_hold_9981"]
    # And they still explain the whole gap.
    assert sum(ours.values()) == canonical["settlement"]["variance"]


def test_the_mdr_split_matches_rail_by_rail(canonical, ledger):
    """The one that was wrong before. Both splits totalled 1,450, so only a
    rail-by-rail comparison catches it."""
    split = canonical["settlement"]["mdr_split"]
    ours = {b.type: b for b in ledger.mdr_bands}

    pairs = [
        ("Credit card and postpaid", "credit_card_and_postpaid"),
        ("Wallet-on-UPI above 2000", "wallet_on_upi_above_2000"),
        ("UPI person-to-merchant", "upi_p2m"),
    ]
    for our_name, their_key in pairs:
        theirs = split[their_key]
        band = ours[our_name]
        assert band.volume_inr == theirs["amount"], our_name
        assert band.fee_inr == theirs["mdr"], our_name
        assert f"{band.rate_percent:g}%" == theirs["mdr_rate"], our_name


def test_loan_terms_match(canonical, ledger):
    loan = canonical["loan"]
    assert ledger.loan.loan_id == loan["loan_id"]
    assert ledger.loan.nbfc == loan["lender"]
    assert ledger.loan.status == loan["edi_status"]
    assert ledger.loan.edi_per_day_inr == loan["daily_edi"]
    assert ledger.loan.balance_inr == loan["outstanding"]
    assert ledger.loan.edi_holiday_eligible == loan["kfs_edi_holiday_eligible"]


def test_mandate_matches(canonical, ledger):
    m = canonical["mandate"]
    ours = ledger.mandate
    assert ours.mandate_id == m["umrn"]
    assert ours.status == m["status"]
    assert ours.last_return_date == m["last_return_date"]
    assert ours.last_return_code == m["last_return_code"]
    assert ours.last_return_reason == m["last_return_reason"]
    assert ours.bounce_charge_inr == m["bounce_charge"]
    assert ours.on_time_rate_percent == m["on_time_rate_percent"]


def test_the_overdue_instalment_matches_the_loan(canonical, ledger):
    assert ledger.mandate.overdue_amount_inr == canonical["loan"]["overdue_amount"]
    assert ledger.mandate.days_past_due == canonical["loan"]["dpd"]


def test_the_chargeback_matches(canonical, ledger):
    cb = canonical["chargebacks"]["CB-9981"]
    assert ledger.chargeback.order_id == cb["order_id"]
    assert ledger.chargeback.amount_held_inr == cb["amount"]
    assert ledger.chargeback.hold_status == cb["status"]


def test_every_canonical_utr_is_in_our_ledger(canonical, ledger):
    for utr, theirs in canonical["utrs"].items():
        assert utr in ledger.utrs, f"{utr} missing from our ledger"
        ours = ledger.utrs[utr]
        # Their file types some amounts as strings; compare numerically.
        assert ours.amount_inr == int(theirs["amount"]), utr
        assert ours.payer_app == theirs["payer_app"], utr
        assert ours.lookup_status == theirs["status"], utr
        if theirs.get("order_id"):
            assert ours.order_id == theirs["order_id"], utr


def test_the_duplicate_pair_is_the_canonical_one(canonical, ledger):
    """The other thing that was invented before: order 4455 instead of 4489."""
    canonical_dupes = {
        utr for utr, v in canonical["utrs"].items() if v.get("order_id") == "4489"
    }
    ours = {t.utr for _, txns in ledger.duplicate_payments() for t in txns}

    assert canonical_dupes == ours
    assert canonical["refunds"]["RFD-DUP-4489"] == "CANDIDATE"  # not yet returned


def test_the_pending_refund_is_still_pending(canonical, ledger):
    assert canonical["refunds"]["RFD-4490"] == "QUEUED"
    assert ledger.orders["4490"].refund_status == "PENDING"
    assert ledger.orders["4490"].in_settlement is False

    assert canonical["refunds"]["RFD-4412"] == "PROCESSED"
    assert ledger.orders["4412"].in_settlement is True


# --- deliberate divergences -----------------------------------------------------------
# Each of these is a place we knowingly differ. Written as assertions so that if the
# dataset ever changes its mind, the test says so instead of staying quietly green.

def test_divergence_we_never_use_the_suspected_fake_label(canonical):
    """The dataset prescribes NOT_FOUND_SUSPECTED_FAKE for an unknown reference.

    This service reports NOT_FOUND with an internal POSSIBLE_FAKE flag instead, and the
    merchant is told the payment is "not in your account". The label is a claim about a
    customer that a database miss cannot support, and the merchant is the one who would
    have to repeat it to their face.
    """
    assert canonical["unknown_utr_status"] == "NOT_FOUND_SUSPECTED_FAKE"

    from app.intents.utr import ADVICE
    assert set(ADVICE) == {"SUCCESS_SETTLED", "PENDING", "FAILED", "REVERSED", "NOT_FOUND"}
    assert "SUSPECTED_FAKE" not in " ".join(ADVICE)


def test_divergence_the_chargeback_deadline_is_relative_not_fixed(canonical, ledger):
    """The dataset pins evidence as due at 2026-11-19T14:05, a snapshot of demo day.

    The contract instead says deadline_iso is reset time plus 48 hours "so the demo
    always has time left", and acceptance case 6 requires step one to ask for a document
    rather than escalate. A fixed timestamp would make that case escalate as urgent
    forever after 02:05 on demo day, so the relative deadline wins and
    /ledger/reset?chargeback_hours_left=N exercises the urgent path on purpose.
    """
    assert canonical["chargebacks"]["CB-9981"]["paytm_evidence_due"].startswith("2026-11-19")

    from app import clock
    assert clock.hours_until(ledger.chargeback.deadline_iso) > 12


def test_divergence_ticket_ids_follow_the_contract_not_the_dataset(canonical):
    """The dataset seeds next_ticket_id as TKT-PAYTM-1291; the contract's ticket schema
    uses tkt_001, which is what Person 3 and Person 4 read."""
    assert canonical["next_ticket_id"].startswith("TKT-PAYTM-")

    from app import store
    store.reset()
    assert store.next_id("tkt") == "tkt_001"
