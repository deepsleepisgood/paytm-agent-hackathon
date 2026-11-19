"""SETTLEMENT_RECONCILE — why less money arrived than the merchant expected.

The most common call, and the demo centrepiece. The merchant knows two numbers: what
they sold and what reached the bank. This explains the difference, line by line.

Worked by all four sub-agents. Note that LedgerOpsAgent is absent: explaining a
settlement never changes anything, and the trace saying so is the proof.
"""
from __future__ import annotations

from .. import templates
from ..errors import PayloadError
from ..mesh import Case


def gather(case: Case) -> str:
    """IntelligenceAgent: pull the settlement the merchant is asking about."""
    payload = case.req.payload or {}
    led = case.ledger

    asked_for = payload.get("settlement_date")
    if asked_for and asked_for != led.settlement_date:
        raise PayloadError(
            f"No settlement for {asked_for}; this merchant's latest is {led.settlement_date}"
        )

    case.data = {
        **led.settlement_as_dict(),
        "upcoming": [
            {
                "label": "Loan instalment",
                "amount_inr": led.loan.edi_due_tomorrow_inr,
                "date": led.loan.next_deduction_date,
            }
        ],
    }
    return (
        f"Read settlement {led.settlement_date}: sold {led.gross_inr}, "
        f"bank credited {led.net_credit_inr}, found {len(led.lines)} deductions"
    )


def assess(case: Case) -> str:
    """RiskPolicyAgent: may we answer this, or is our picture incomplete?"""
    led = case.ledger

    if led.reconciles:
        return (
            f"Deductions total {led.lines_total_inr} and the gap is {led.variance_inr}: "
            "they match, so this can be explained without a human"
        )

    unaccounted = abs(led.variance_inr - led.lines_total_inr)
    case.escalate(
        "SETTLEMENT_UNRECONCILED",
        f"Breakdown does not explain the variance: lines total {led.lines_total_inr} "
        f"against a gap of {led.variance_inr}",
    )
    return (
        f"Deductions total {led.lines_total_inr} but the gap is {led.variance_inr}: "
        f"{unaccounted} unaccounted for, so a human must look"
    )


def resolve(case: Case) -> str:
    """ResolutionAgent: the answer, and the words the merchant hears."""
    led = case.ledger

    if case.escalated:
        case.found = (
            f"Deductions total {led.lines_total_inr} but the gap is "
            f"{led.variance_inr}: {abs(led.variance_inr - led.lines_total_inr)} unaccounted for"
        )
        case.action_taken = "Explained nothing; the breakdown is incomplete"
        case.tried = ["Pulled the settlement breakdown from the ledger"]
        case.template_text = templates.render("SETTLEMENT_RECONCILE", case.data, "ESCALATED")
        return "Told the merchant the gap is real but not fully explained, and handed it over"

    parts = " + ".join(f"{l['code']} {l['amount_inr']}" for l in led.lines)
    case.found = f"Gap {led.variance_inr} = {parts}"
    case.action_taken = "None, explained only"
    case.template_text = templates.render("SETTLEMENT_RECONCILE", case.data, "RESOLVED")
    return f"Explained all {len(led.lines)} deductions, and flagged tomorrow's loan instalment"
