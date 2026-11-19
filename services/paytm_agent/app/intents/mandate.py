"""MANDATE_TROUBLESHOOT — the auto-debit for today's loan instalment bounced.

A bounce letter is frightening. The merchant's bank balance ran out for a few hours, and
what lands is a notice that reads like default. The useful thing an agent can do here is
mostly not arithmetic: it is to say what actually happened, put it in the context of
their own repayment record, and offer the two ways out.

sarvam_service's Hindi reply for this scenario opens with "do not panic, this is not a
default" and cites 96% of instalments on time over six months. The data here carries
exactly those figures so the two services cannot tell the merchant different stories.

Two remedies:
  pay now      a UPI link for the missed instalment, which the merchant can always do
  pause        one hardship pause under the KFS, if they have not used one recently

The agent offers both and does neither. Paying is the merchant's action, and the pause
runs through /a2a/execute-edi-pause so it carries a consent artifact.
"""
from __future__ import annotations

from .. import store, templates
from ..config import HARDSHIP_PAUSES_PER_WINDOW, HARDSHIP_PAUSE_WINDOW_DAYS
from ..errors import PayloadError
from ..mesh import Case


def gather(case: Case) -> str:
    """IntelligenceAgent: what bounced, why, and what this merchant's record looks like."""
    payload = case.req.payload or {}
    m = case.ledger.mandate

    asked = payload.get("mandate_id")
    if asked and asked != m.mandate_id:
        raise PayloadError(f"No mandate {asked!r}; this merchant's is {m.mandate_id}")

    case.data = {
        "mandate_id": m.mandate_id,
        "status": m.status,
        "amount_inr": m.amount_inr,
        "last_return_date": m.last_return_date,
        "last_return_reason": m.last_return_reason,
        "last_return_code": m.last_return_code,
        "overdue_amount_inr": m.overdue_amount_inr,
        "days_past_due": m.days_past_due,
        "bounce_charge_inr": m.bounce_charge_inr,
        "is_default": False,
        "repayment_history": {
            "on_time_rate_percent": m.on_time_rate_percent,
            "months": m.history_months,
        },
        "nbfc": case.ledger.loan.nbfc,
    }

    if not m.needs_remedy:
        return f"Read mandate {m.mandate_id}: {m.status}, nothing outstanding"

    return (
        f"Read mandate {m.mandate_id}: {m.amount_inr} presentment returned on "
        f"{m.last_return_date} ({m.last_return_reason}); {m.on_time_rate_percent}% on time over "
        f"{m.history_months} months"
    )


def assess(case: Case) -> str:
    """RiskPolicyAgent: which remedies may be offered without a human."""
    m = case.ledger.mandate
    loan = case.ledger.loan
    data = case.data

    if not m.needs_remedy:
        data["remedies"] = []
        return "Nothing outstanding, so there is nothing to remedy"

    # Paying the missed instalment is always available: it is the merchant's own money
    # moving on their own instruction.
    remedies = [{
        "type": "PAY_NOW_UPI_LINK",
        "amount_inr": m.amount_inr,
        "valid_hours": 24,
        "label": "Pay today's instalment by UPI link",
    }]

    pauses_left = HARDSHIP_PAUSES_PER_WINDOW - m.hardship_pauses_used_in_window
    pause_eligible = (
        loan.edi_holiday_eligible and loan.status == "ACTIVE" and pauses_left > 0
    )

    if pause_eligible:
        offer = {
            "offer_id": store.next_code("EDIOFFER"),
            "eligible": True,
            "nbfc": loan.nbfc,
            "pause_days": loan.max_pause_days,
            "edi_saved_inr": loan.edi_per_day_inr * loan.max_pause_days,
            "kfs_clause": loan.kfs_clause,
        }
        # Registered so the merchant's consent can be matched to the offer they saw.
        store.edi_offers[offer["offer_id"]] = offer
        remedies.append({
            "type": "KFS_HARDSHIP_PAUSE",
            "label": f"Pause the instalment for {loan.max_pause_days} days",
            **offer,
        })
    data["remedies"] = remedies
    data["hardship_pause_eligible"] = pause_eligible

    if not pause_eligible:
        # Still answerable: the merchant can pay. But a second hardship request inside
        # the window is a sign of real trouble, and a person should look at the account
        # rather than the agent quietly refusing.
        case.escalate(
            "OUT_OF_SCOPE",
            f"Instalment unpaid and no hardship pause is available "
            f"({m.hardship_pauses_used_in_window} already used in "
            f"{HARDSHIP_PAUSE_WINDOW_DAYS} days, or the EDI is {loan.status})",
        )
        return (
            f"Returned, but no pause left in {HARDSHIP_PAUSE_WINDOW_DAYS} days: "
            "offer the UPI link and let a person look at the account"
        )

    return (
        f"Returned once with {m.on_time_rate_percent}% on time and {m.days_past_due} days past due: not a default, and a "
        f"{loan.max_pause_days}-day pause is available under KFS {loan.kfs_clause}"
    )


def resolve(case: Case) -> str:
    """ResolutionAgent: explain it is fixable, and offer the two ways out."""
    m = case.ledger.mandate
    data = case.data

    if not m.needs_remedy:
        case.found = f"Mandate {m.mandate_id} is {m.status} with nothing outstanding"
        case.action_taken = "None, explained only"
        case.template_text = templates.render("MANDATE_TROUBLESHOOT", data, case.status)
        return "Told the merchant the mandate is healthy"

    case.found = (
        f"{m.mandate_id} returned {m.amount_inr} on {m.last_return_date} ({m.last_return_reason}); "
        f"{m.on_time_rate_percent}% on time over {m.history_months} months"
    )

    if case.escalated:
        case.action_taken = "Offered the UPI link; hardship pause needs a person"
        case.tried = [
            "Explained the bounce is not a default",
            "Offered a UPI link for the missed instalment",
        ]
        case.template_text = templates.render("MANDATE_TROUBLESHOOT", data, "ESCALATED")
        return "Offered the link, and asked a person to look at the repayment history"

    # The merchant has to choose, so the case is not closed.
    case.status = "ACTION_REQUIRED"
    case.action_required = {
        "type": "CHOOSE_REMEDY",
        "options": [r["type"] for r in data["remedies"]],
        "amount_inr": m.amount_inr,
    }
    case.action_taken = "Explained the bounce and offered two remedies"
    case.template_text = templates.render("MANDATE_TROUBLESHOOT", data, "ACTION_REQUIRED")
    return "Explained it is not a default, and offered a UPI link or a 2-day pause"
