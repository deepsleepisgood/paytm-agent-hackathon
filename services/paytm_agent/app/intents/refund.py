"""REFUND_MANAGE — the status of a refund, or a request to start one.

Kept deliberately thin. It is a contract v1 intent that the scenario table replaced with
DUPLICATE_PAYMENT_RECONCILE, but sarvam_service still routes to it and the contract
still lists it, so answering it is cheaper than the integration failing.

Status questions are answered. Starting a refund is money leaving on a judgement call,
not a provable double charge, so the bar is the lower REFUND_AUTO_LIMIT_INR and anything
outside it goes to a person.
"""
from __future__ import annotations

from .. import templates
from ..config import REFUND_AUTO_LIMIT_INR
from ..errors import PayloadError
from ..mesh import Case

ACTIONS = ("STATUS", "INITIATE")


def gather(case: Case) -> str:
    payload = case.req.payload or {}
    led = case.ledger

    action = str(payload.get("action") or "STATUS").upper()
    if action not in ACTIONS:
        raise PayloadError(f"action must be one of {list(ACTIONS)}")

    order_id = str(payload.get("order_id") or "").lstrip("#").strip()
    if not order_id:
        raise PayloadError("REFUND_MANAGE needs an order_id")

    order = led.orders.get(order_id)
    case.data = {
        "order_id": order_id,
        "action": action,
        "found": order is not None,
        "refund_status": order.refund_status if order else "NONE",
        "amount_inr": (order.refund_amount_inr or order.amount_inr) if order else
                      payload.get("amount_inr"),
        "order_amount_inr": order.amount_inr if order else None,
    }
    if order is None:
        return f"Order {order_id} is not in this merchant's ledger"
    return (
        f"Read order {order_id}: {order.amount_inr}, refund {order.refund_status}"
    )


def assess(case: Case) -> str:
    data = case.data

    if not data["found"]:
        case.escalate("ORDER_NOT_FOUND", f"Order {data['order_id']} is not in the ledger")
        return "No such order, so there is nothing to check or refund"

    if data["action"] == "STATUS":
        return f"A status question about order {data['order_id']}: safe to answer"

    if data["refund_status"] == "PROCESSED":
        case.escalate(
            "OUT_OF_SCOPE",
            f"Order {data['order_id']} has already been refunded; a second refund is "
            "not something the agent will start",
        )
        return "Already refunded once: a second refund needs a person"

    amount = int(case.req.payload.get("amount_inr") or data["amount_inr"] or 0)
    data["requested_amount_inr"] = amount
    data["within_auto_limit"] = amount <= REFUND_AUTO_LIMIT_INR

    if amount > (data["order_amount_inr"] or 0):
        case.escalate(
            "OUT_OF_SCOPE",
            f"Refund of {amount} is more than the {data['order_amount_inr']} paid for "
            f"order {data['order_id']}",
        )
        return "Asked to refund more than the customer paid: a person must look"

    if not data["within_auto_limit"]:
        case.escalate(
            "REFUND_OVER_LIMIT",
            f"Refund of {amount} on order {data['order_id']} is above the "
            f"{REFUND_AUTO_LIMIT_INR} the agent may approve alone",
        )
        return (
            f"{amount} is over the {REFUND_AUTO_LIMIT_INR} limit: money leaving on a "
            "judgement call is a person's decision"
        )

    return f"{amount} is within the {REFUND_AUTO_LIMIT_INR} limit: safe to start"


def resolve(case: Case) -> str:
    data = case.data

    if case.escalated:
        case.found = case.reason_text
        case.action_taken = "Nothing refunded; handed to a person"
        case.tried = ["Checked the order against the ledger"]
        case.template_text = templates.render("REFUND_MANAGE", data, "ESCALATED")
        return "Explained the position and handed it over"

    if data["action"] == "STATUS":
        case.found = f"Order {data['order_id']} refund is {data['refund_status']}"
        case.action_taken = "None, explained only"
        case.template_text = templates.render("REFUND_MANAGE", data, "RESOLVED")
        return f"Reported the refund as {data['refund_status']}"

    case.found = (
        f"Started a refund of {data['requested_amount_inr']} on order {data['order_id']}"
    )
    case.action_taken = "Started the refund"
    case.template_text = templates.render("REFUND_MANAGE", data, "RESOLVED")
    return "Confirmed the refund is on its way to the customer"


def apply(case: Case) -> str | None:
    """LedgerOpsAgent: only an approved INITIATE moves anything."""
    if case.status != "RESOLVED" or case.data.get("action") != "INITIATE":
        return None

    order = case.ledger.orders[case.data["order_id"]]
    order.refund_status = "PENDING"
    order.refund_amount_inr = case.data["requested_amount_inr"]
    order.in_settlement = False  # today's refund, not one of yesterday's deductions
    case.data["refund_status"] = "PENDING"

    return (
        f"Queued a refund of {case.data['requested_amount_inr']} to the customer on "
        f"order {case.data['order_id']}"
    )
