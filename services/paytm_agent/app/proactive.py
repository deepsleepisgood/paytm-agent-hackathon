"""The V2 delta: Paytm speaking first.

Everything else in this service answers a merchant who has already noticed a problem.
These two operations run the other way round — Paytm spots the problem and reaches out
before the merchant knows about it:

  /a2a/proactive-alert     "a dispute just landed" / "tomorrow's payout will be short"
  /a2a/execute-edi-pause   the merchant said yes, so pause the loan repayment

Two deliberate differences from /a2a/dispatch, both straight from the contract:

**The alert needs no consent token.** It only informs the merchant about their own
account and shares nothing with anyone. Consent is required at the moment something is
actually *done* — which is the pause, and that one does demand a token.

**Alerts are not call summaries.** A proactive alert is not a call the merchant made, so
it is kept out of the call feed. Counting it there would inflate calls_total and make
the auto-resolution rate describe something other than merchant calls.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import clock, repository, store
from .errors import error_body

TRIGGERS = ("CHARGEBACK_INCOMING", "HIGH_REFUND_CASHFLOW")


def _alert_envelope(alert_id: str, intent: str, trigger_type: str,
                    data: dict, action_required: dict) -> dict:
    """The same envelope as /a2a/dispatch, plus alert_id and trigger_type."""
    return {
        "alert_id": alert_id,
        "status": "ALERT_RAISED",
        "intent": intent,
        "trigger_type": trigger_type,
        "data": data,
        "action_required": action_required,
        "escalation_ticket": None,
    }


def raise_alert(mid: str, trigger_type: str) -> tuple[dict, int]:
    ledger = store.ledger

    if mid != ledger.mid:
        return error_body("UNKNOWN_MID", f"No merchant {mid!r} in this service"), 404
    if trigger_type not in TRIGGERS:
        return error_body(
            "BAD_PAYLOAD", f"trigger_type must be one of {list(TRIGGERS)}"
        ), 400

    if trigger_type == "CHARGEBACK_INCOMING":
        cb = ledger.chargeback
        alert_id = f"ALERT-{cb.txn_id}"
        # Raising the same alert twice must not produce a second one: the frontend
        # simulates the webhook, and a rehearsed demo clicks it more than once.
        if alert_id in store.alerts:
            return store.alerts[alert_id], 200

        hours = int(round(clock.hours_until(cb.deadline_iso)))
        envelope = _alert_envelope(
            alert_id,
            intent="CHARGEBACK_RESOLVE",
            trigger_type=trigger_type,
            data={
                "txn_id": cb.txn_id,
                "order_id": cb.order_id,
                "amount": cb.amount_held_inr,
                "deadline_hours": hours,
            },
            action_required={
                "type": "SUBMIT_POD",
                "message": f"Submit Proof of Delivery within {hours}h",
            },
        )
        store.alerts[alert_id] = envelope
        return envelope, 200

    # HIGH_REFUND_CASHFLOW — a refund is about to leave the payout short.
    refund_order = next(
        (o for o in ledger.orders.values() if o.refund_status == "PENDING"), None
    )
    if refund_order is None:
        return error_body("NOT_FOUND", "No pending refund to raise a cashflow alert for"), 404

    alert_id = f"ALERT-{refund_order.order_id}"
    if alert_id in store.alerts:
        return store.alerts[alert_id], 200

    loan = ledger.loan
    pause_days = loan.max_pause_days
    eligible = loan.edi_holiday_eligible and loan.status == "ACTIVE"

    offer = {
        "offer_id": store.next_code("EDIOFFER"),
        "eligible": eligible,
        "nbfc": loan.nbfc,
        "pause_days": pause_days,
        "edi_saved_inr": loan.edi_per_day_inr * pause_days,
        "kfs_clause": loan.kfs_clause,
    }
    store.edi_offers[offer["offer_id"]] = offer

    envelope = _alert_envelope(
        alert_id,
        intent="FEE_GST_LOAN",
        trigger_type=trigger_type,
        data={
            "refund_request": {
                "order_id": refund_order.order_id,
                "amount": refund_order.refund_amount_inr,
            },
            "projected_net_payout": ledger.projected_net_payout_inr(),
            "edi_pause_offer": offer,
        },
        action_required={
            "type": "CONFIRM_EDI_PAUSE",
            "message": "Merchant consent needed to pause EDI",
        },
    )
    store.alerts[alert_id] = envelope
    return envelope, 200


def execute_edi_pause(mid: str, consent_token: str | None,
                      pause_days: int, offer_id: str | None) -> tuple[dict, int]:
    ledger = store.ledger
    loan = ledger.loan

    # Consent first: this one actually changes a credit arrangement. 403, not 400 —
    # the contract's DPDP guardrail.
    if not (consent_token or "").strip():
        return error_body("DPDP_CONSENT_REQUIRED", "A DPDP consent token is required"), 403

    if mid != ledger.mid:
        return error_body("UNKNOWN_MID", f"No merchant {mid!r} in this service"), 404

    offer = store.edi_offers.get(offer_id or "")
    if offer is None:
        return error_body(
            "EDI_PAUSE_NOT_ELIGIBLE",
            f"No EDI pause offer {offer_id!r}; raise a HIGH_REFUND_CASHFLOW alert first",
        ), 409
    if not offer["eligible"]:
        return error_body("EDI_PAUSE_NOT_ELIGIBLE", "That offer is not eligible"), 409
    if loan.status != "ACTIVE":
        return error_body(
            "EDI_PAUSE_NOT_ELIGIBLE", f"The EDI is already {loan.status}"
        ), 409
    if pause_days > loan.max_pause_days:
        return error_body(
            "EDI_PAUSE_NOT_ELIGIBLE",
            f"KFS clause {loan.kfs_clause} allows at most "
            f"{loan.max_pause_days} days, not {pause_days}",
        ), 409
    if pause_days < 1:
        return error_body("EDI_PAUSE_NOT_ELIGIBLE", "pause_days must be at least 1"), 409

    # The database re-checks the KFS rules and writes the pause, lender approval and consent
    # artifact in one transaction. It runs first, so a rejection there leaves memory untouched.
    try:
        repository.pause_edi(mid, pause_days, loan.kfs_clause, offer_id, consent_token)
    except repository.DbRuleError as exc:
        if exc.code == "CONSENT_INVALID":
            return error_body("DPDP_CONSENT_REQUIRED", f"consent token is {exc.detail.lower()}"), 403
        return error_body("EDI_PAUSE_NOT_ELIGIBLE", exc.detail), 409

    # --- the mutation ------------------------------------------------------------------
    resume = date.fromisoformat(loan.next_deduction_date) + timedelta(days=pause_days)

    artifact = {
        "artifact_id": store.next_code("KFS-ART"),
        "clause": loan.kfs_clause,
        "consent_token": consent_token,
        "ts": int(clock.now().timestamp()),
    }

    loan.status = f"PAUSED_{pause_days}_DAYS"
    loan.paused_days = pause_days
    loan.resume_date = resume.isoformat()
    loan.consent_artifact = artifact

    return {
        "status": "EDI_PAUSED",
        "intent": "FEE_GST_LOAN",
        "data": {
            "loan_edi_status": loan.status,
            "nbfc": loan.nbfc,
            "pause_days": pause_days,
            "edi_saved_inr": loan.edi_per_day_inr * pause_days,
            "edi_tomorrow": loan.edi_due_tomorrow_inr,
            "resume_date": loan.resume_date,
            "kfs_consent_artifact": artifact,
        },
        "action_required": None,
        "escalation_ticket": None,
    }, 200
