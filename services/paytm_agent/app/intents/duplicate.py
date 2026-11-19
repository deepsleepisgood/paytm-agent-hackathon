"""DUPLICATE_PAYMENT_RECONCILE — a customer paid twice for one order.

The clearest case in the whole service, and the one where the agent can safely move
money. A duplicate is not a judgement call: the ledger holds two settled payments
against one order id, seconds apart. There is nothing to weigh up, so the auto limit is
higher here than for a discretionary refund.

The money is returned to the **customer**, not to the merchant, and the merchant's own
position does not change: they were credited twice, so taking one back leaves them
exactly where they should have been. sarvam_service's Hindi reply says the same thing —
"your accounts are square" — and that is why nothing in the settlement or the projected
payout moves.

Which one goes back: the later payment, so the first one keeps its place in the
settlement that already ran.
"""
from __future__ import annotations

from .. import templates
from ..config import DUPLICATE_AUTO_LIMIT_INR
from ..errors import PayloadError
from ..mesh import Case


def gather(case: Case) -> str:
    """IntelligenceAgent: find orders that were genuinely paid for more than once."""
    payload = case.req.payload or {}
    led = case.ledger

    asked = payload.get("order_id")
    pairs = led.duplicate_payments()
    if asked:
        asked = str(asked).lstrip("#").strip()
        pairs = [p for p in pairs if p[0] == asked]
        if not pairs and asked not in led.orders:
            raise PayloadError(f"No order {asked!r} in this merchant's ledger")

    if not pairs:
        case.data = {"duplicates_found": 0, "order_id": asked, "payments": []}
        return (
            f"Checked {asked or 'the ledger'}: no order has more than one settled payment"
        )

    order_id, txns = pairs[0]
    first, later = txns[0], txns[-1]

    case.data = {
        "duplicates_found": len(pairs),
        "order_id": order_id,
        "order_amount_inr": led.orders[order_id].amount_inr if order_id in led.orders else None,
        "payments": [t.as_dict() for t in txns],
        "keep": {"utr": first.utr, "amount_inr": first.amount_inr,
                 "received_at": first.received_at},
        "refund": {"utr": later.utr, "amount_inr": later.amount_inr,
                   "received_at": later.received_at, "payer_app": later.payer_app},
        "already_refunded": later.refunded,
    }
    return (
        f"Order {order_id} has {len(txns)} settled payments of {later.amount_inr}: "
        f"{first.utr} then {later.utr}"
    )


def assess(case: Case) -> str:
    """RiskPolicyAgent: a provable double charge, so the only question is the amount."""
    data = case.data

    if data["duplicates_found"] == 0:
        return "Nothing to reconcile: no duplicate payments found"

    if data["already_refunded"]:
        return f"The second payment {data['refund']['utr']} was already returned"

    amount = data["refund"]["amount_inr"]
    data["within_auto_limit"] = amount <= DUPLICATE_AUTO_LIMIT_INR

    if not data["within_auto_limit"]:
        case.escalate(
            "REFUND_OVER_LIMIT",
            f"Duplicate payment of {amount} on order {data['order_id']} is above the "
            f"{DUPLICATE_AUTO_LIMIT_INR} the agent may return alone",
        )
        return (
            f"A genuine duplicate, but {amount} is over the "
            f"{DUPLICATE_AUTO_LIMIT_INR} limit: a person must release it"
        )

    return (
        f"Two settled payments on one order is a provable double charge, and {amount} "
        f"is within the {DUPLICATE_AUTO_LIMIT_INR} limit: safe to return"
    )


def resolve(case: Case) -> str:
    """ResolutionAgent: reassure the merchant that their own position is unchanged."""
    data = case.data

    if data["duplicates_found"] == 0:
        case.found = "No duplicate payments found"
        case.action_taken = "None, explained only"
        case.template_text = templates.render("DUPLICATE_PAYMENT_RECONCILE", data, "RESOLVED")
        return "Told the merchant nothing was charged twice"

    if data["already_refunded"]:
        case.found = f"Duplicate on order {data['order_id']} was already returned"
        case.action_taken = "None, explained only"
        case.template_text = templates.render("DUPLICATE_PAYMENT_RECONCILE", data, "RESOLVED")
        return "Told the merchant it had already been put right"

    if case.escalated:
        case.found = (
            f"Duplicate of {data['refund']['amount_inr']} on order {data['order_id']}, "
            "above the agent's limit"
        )
        case.action_taken = "Nothing returned; handed to a person"
        case.tried = ["Confirmed two settled payments against one order"]
        case.template_text = templates.render("DUPLICATE_PAYMENT_RECONCILE", data, "ESCALATED")
        return "Confirmed the double charge, and asked a person to release the refund"

    case.found = (
        f"Order {data['order_id']} paid twice; returning {data['refund']['amount_inr']} "
        f"({data['refund']['utr']}) to the customer"
    )
    case.action_taken = "Returned the duplicate payment to the customer"
    case.template_text = templates.render("DUPLICATE_PAYMENT_RECONCILE", data, "RESOLVED")
    return "Confirmed the duplicate is going back and the merchant is square"


def apply(case: Case) -> str | None:
    """LedgerOpsAgent: return the later payment to the customer."""
    if case.status != "RESOLVED" or case.data.get("duplicates_found", 0) == 0:
        return None
    if case.data.get("already_refunded") or not case.data.get("within_auto_limit"):
        return None

    led = case.ledger
    refund = case.data["refund"]
    txn = led.utrs[refund["utr"]]
    txn.refunded = True

    order = led.orders.get(case.data["order_id"])
    if order is not None:
        order.refund_status = "PROCESSED"
        order.refund_amount_inr = refund["amount_inr"]
        # Not in_settlement: this refund is happening today, and marking it otherwise
        # would make a settlement that has already closed stop reconciling.
        order.in_settlement = False

    case.data["refund_status"] = "PROCESSED"
    case.data["merchant_position_changed"] = False

    return (
        f"Returned {refund['amount_inr']} on {refund['utr']} to the customer; "
        "the merchant was credited twice, so their own position is unchanged"
    )
