"""CASHFLOW_EDI_SWITCH — "tomorrow's payout is short, can the instalment wait?"

The reactive twin of the proactive cashflow alert built in proactive.py. Same facts,
same offer, same execution path; the only difference is who spoke first. Here the
merchant asks, because they have looked at tomorrow's payout and their supplier bill.

What this intent does **not** do is pause anything. It works out the projection, checks
the KFS eligibility, and hands back an offer with an offer_id. The pause itself goes
through /a2a/execute-edi-pause, which demands a consent token and writes a KFS consent
artifact — because changing the terms of someone's credit on a voice request, with no
record of their agreement, is not a thing to do quietly.

It also does not know what the merchant owes their supplier. Those payables live in the
merchant's Vyapar connector, which the contract is explicit that Paytm never reads.
Person 3 holds that figure and works out the shortfall; we supply the payout projection
and the offer.
"""
from __future__ import annotations

from .. import store, templates
from ..mesh import Case


def gather(case: Case) -> str:
    """IntelligenceAgent: what tomorrow's payout looks like and why."""
    led = case.ledger
    loan = led.loan

    case.data = {
        "projected_net_payout": led.projected_net_payout_inr(),
        "breakdown": {
            "expected_gross_inr": led.projected_gross_tomorrow_inr,
            "pending_refunds_inr": led.pending_refund_inr,
            "edi_due_inr": loan.edi_due_tomorrow_inr,
            "released_hold_inr": (
                led.chargeback.amount_held_inr
                if led.chargeback.hold_status == "RELEASED" else 0
            ),
        },
        "loan_edi_status": loan.status,
        "nbfc": loan.nbfc,
        # The projection nets the EDI off the payout because the contract's 1,200 figure
        # does, and Person 1's recorded reply and Person 3's code both depend on it. The
        # canonical loan data says the EDI is actually collected by eNACH from the bank
        # account, so the collection method travels with the number rather than the
        # discrepancy being hidden.
        "edi_collection_method": loan.collection_method,
        # Deliberately absent: tomorrow_stock_due and the shortfall. Those come from the
        # merchant's Vyapar connector, which lives on 8003 and which Paytm does not read.
        "payables_known_to_paytm": False,
    }
    return (
        f"Projected tomorrow's payout at {case.data['projected_net_payout']}: "
        f"{led.projected_gross_tomorrow_inr} expected, less "
        f"{led.pending_refund_inr} in refunds and {loan.edi_due_tomorrow_inr} EDI"
    )


def assess(case: Case) -> str:
    """RiskPolicyAgent: is a KFS hardship pause available on this loan today?"""
    loan = case.ledger.loan
    data = case.data

    if loan.status != "ACTIVE":
        data["edi_pause_offer"] = {"eligible": False, "reason": f"EDI is {loan.status}"}
        return f"The EDI is already {loan.status}, so there is nothing further to pause"

    if not loan.edi_holiday_eligible:
        data["edi_pause_offer"] = {
            "eligible": False, "reason": "This loan is not eligible for an EDI holiday",
        }
        case.escalate(
            "OUT_OF_SCOPE",
            f"{loan.nbfc} loan is not eligible for an EDI holiday, so any relief is a "
            "conversation with the lender",
        )
        return "Not eligible for a pause under the KFS: a person should talk to the lender"

    offer = {
        "offer_id": store.next_code("EDIOFFER"),
        "eligible": True,
        "nbfc": loan.nbfc,
        "pause_days": loan.max_pause_days,
        "edi_saved_inr": loan.edi_per_day_inr * loan.max_pause_days,
        "kfs_clause": loan.kfs_clause,
    }
    # Registered so /a2a/execute-edi-pause can match the merchant's consent to the
    # offer they were actually shown. Recording an offer is not a change to the
    # merchant's account, so it stays here rather than in LedgerOpsAgent; the pause
    # itself is still gated behind a consent token.
    store.edi_offers[offer["offer_id"]] = offer
    data["edi_pause_offer"] = offer
    return (
        f"Eligible for a {loan.max_pause_days}-day pause under KFS {loan.kfs_clause}, "
        f"worth {data['edi_pause_offer']['edi_saved_inr']} to tomorrow's cashflow"
    )


def resolve(case: Case) -> str:
    """ResolutionAgent: show the projection and offer the pause, nothing more."""
    data = case.data
    offer = data["edi_pause_offer"]

    if case.escalated:
        case.found = f"Payout projected at {data['projected_net_payout']}; no pause available"
        case.action_taken = "Explained the projection; relief needs the lender"
        case.tried = ["Projected tomorrow's payout", "Checked KFS eligibility"]
        case.template_text = templates.render("CASHFLOW_EDI_SWITCH", data, "ESCALATED")
        return "Explained the shortfall and handed the lender question to a person"

    case.found = (
        f"Payout projected at {data['projected_net_payout']}"
        + (f"; offered a {offer['pause_days']}-day EDI pause saving "
           f"{offer['edi_saved_inr']}" if offer.get("eligible") else "; no pause available")
    )

    if not offer.get("eligible"):
        case.action_taken = "None, explained only"
        case.template_text = templates.render("CASHFLOW_EDI_SWITCH", data, "RESOLVED")
        return "Explained the projection; the EDI is already paused"

    # The merchant has to consent, so this is not closed.
    case.status = "ACTION_REQUIRED"
    case.action_required = {
        "type": "CONFIRM_EDI_PAUSE",
        "message": "Merchant consent needed to pause EDI",
        "offer_id": offer["offer_id"],
        "pause_days": offer["pause_days"],
    }
    case.action_taken = "Offered a KFS hardship pause, awaiting consent"
    case.template_text = templates.render("CASHFLOW_EDI_SWITCH", data, "ACTION_REQUIRED")
    return (
        f"Offered the {offer['pause_days']}-day pause and asked for consent; the pause "
        "itself runs through /a2a/execute-edi-pause"
    )


def apply(case: Case) -> str | None:
    """LedgerOpsAgent: nothing. Pausing credit needs a recorded consent, not a chat."""
    return None
