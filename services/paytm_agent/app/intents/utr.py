"""UTR_VERIFY — "a customer showed me a payment. Did it actually arrive?"

The scenario where the wording matters more than the logic. A shopkeeper is standing in
front of a customer holding up a screenshot, and the agent's answer decides whether the
goods leave the shop.

Three things this module will not do:

  It will not call anything fake. A reference we cannot find means "not in your
  account", which is what the ledger can actually prove. The customer may have
  mistyped, used another account, or the payment may still be in flight. Calling it
  fake accuses a named person on the strength of a database miss, and the merchant is
  the one who then has to say it out loud to their customer.

  It will not treat a screenshot as proof. Person 1's reader extracts text from an
  image; that is a hint about what the picture says, never evidence that money moved.
  Only the ledger lookup decides.

  It will not call a pending payment a failure. Pending reverses by itself if it fails,
  so the honest advice is to wait, not to panic.

The one escalation here is a pattern, not a single lookup: several unknown references in
one conversation is what an attempt on the merchant looks like, and a human should ring
them before they hand over stock.
"""
from __future__ import annotations

from .. import templates
from ..config import UNKNOWN_UTR_LIMIT
from ..errors import PayloadError
from ..mesh import Case

# lookup_status -> what the merchant should do about it.
ADVICE = {
    "SUCCESS_SETTLED": "RELEASE_GOODS",
    "PENDING": "WAIT",
    "NOT_FOUND": "DO_NOT_RELEASE_YET",
}


def gather(case: Case) -> str:
    """IntelligenceAgent: look the reference up in the merchant's own ledger."""
    payload = case.req.payload or {}

    utr = str(payload.get("utr") or "").strip()
    if not utr:
        raise PayloadError("UTR_VERIFY needs a utr")

    claimed = payload.get("claimed_amount_inr")
    if claimed is not None and not isinstance(claimed, (int, float)):
        raise PayloadError("claimed_amount_inr must be a number")

    # "voice" when the merchant read the number out, "screenshot" when it came off an
    # image. Recorded, never trusted: it changes nothing about the lookup.
    source = (payload.get("source") or "voice").lower()

    txn = case.ledger.utrs.get(utr)
    if txn is None:
        case.data = {
            "utr": utr,
            "lookup_status": "NOT_FOUND",
            "amount_inr": None,
            "payer_app": None,
            "amount_matches_claim": False if claimed is not None else None,
            "advice": ADVICE["NOT_FOUND"],
            # For the risk dashboard's count only. Never spoken, never put in a ticket.
            "internal_flag": "POSSIBLE_FAKE",
            "source": source,
        }
        return f"Looked up {utr}: not present in this merchant's account"

    case.data = {
        "utr": utr,
        "lookup_status": txn.lookup_status,
        "amount_inr": txn.amount_inr,
        "payer_app": txn.payer_app,
        "amount_matches_claim": (
            None if claimed is None else int(claimed) == txn.amount_inr
        ),
        "advice": ADVICE[txn.lookup_status],
        "internal_flag": None,
        "source": source,
    }
    return (
        f"Looked up {utr}: {txn.lookup_status}, {txn.amount_inr} via {txn.payer_app}"
    )


def assess(case: Case) -> str:
    """RiskPolicyAgent: answer it, unless this conversation looks like an attempt."""
    data = case.data
    session = case.session

    if data["lookup_status"] != "NOT_FOUND":
        if data["amount_matches_claim"] is False:
            return (
                f"Found and {data['lookup_status']}, but the amount does not match what "
                "the merchant was told; worth saying so, still safe to answer"
            )
        return f"Found and {data['lookup_status']}: safe to answer without a human"

    # Count the lookups, not the distinct references: a customer reading the same bogus
    # number three times is the same warning sign as three different ones.
    session.unknown_utr_count += 1
    case.fraud_event = {"kind": "UNKNOWN_UTR", "utr": data["utr"]}

    if session.unknown_utr_count >= UNKNOWN_UTR_LIMIT:
        case.escalate(
            "REPEATED_UNKNOWN_UTR",
            f"{session.unknown_utr_count} payment references in this conversation were "
            "not found in the merchant's account",
        )
        return (
            f"{session.unknown_utr_count} unknown references in one conversation, at or "
            f"over the limit of {UNKNOWN_UTR_LIMIT}: a person should call the merchant"
        )

    return (
        f"Not found, and {session.unknown_utr_count} of "
        f"{UNKNOWN_UTR_LIMIT} in this conversation: answer it, but advise holding the goods"
    )


def resolve(case: Case) -> str:
    """ResolutionAgent: tell the merchant what to do, without accusing anyone."""
    data = case.data
    status = data["lookup_status"]

    if case.escalated:
        case.found = (
            f"{case.session.unknown_utr_count} references not found in this conversation"
        )
        case.action_taken = "Advised holding the goods and raised it with a person"
        case.tried = [
            f"Checked {case.session.unknown_utr_count} references against the ledger",
            "Advised the merchant not to hand over goods",
        ]
        case.template_text = templates.render("UTR_VERIFY", data, "ESCALATED")
        return "Advised holding the goods, and asked a colleague to call the merchant"

    case.found = (
        f"{data['utr']} is {status}"
        + (f", {data['amount_inr']} via {data['payer_app']}" if data["amount_inr"] else "")
    )
    case.action_taken = f"Checked the ledger and advised {data['advice']}"
    case.template_text = templates.render("UTR_VERIFY", data, "RESOLVED")
    return f"Reported {status} and advised {data['advice']}"
