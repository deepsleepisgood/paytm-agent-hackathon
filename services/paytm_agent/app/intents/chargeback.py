"""CHARGEBACK_RESOLVE — a customer disputed a payment, and 800 is being held.

Two steps. First the merchant is told what is held and by when they must prove delivery.
Then they upload a proof of delivery, and if it stands up, the evidence is submitted and
the hold released.

This is the only intent so far where LedgerOpsAgent acts, so it is also the one where
the order of the checks matters.

**Check precedence: deadline, then confidence, then the fields.** These can all be true
at once, and whichever fires first is what the employee reads on the ticket. Deadline
goes first because it is the only one a human can still do something about by picking up
the phone; a bad document with three hours left is a deadline problem before it is a
document problem.

**Payload tolerance.** Two specs in this team describe this payload differently, and
Person 1's document reader uses a third field name again:

    contract v2 delta   {order_id, txn_id, pod_submitted, pod_document, pod_source}
    the richer spec     {txn_id, doc: {doc_type, extracted_fields, confidence}}
    sarvam /doc-extract returns `amount`, where both specs say `amount_inr`

Rather than pick one and break at integration, all of them are read. The cost is one
small normalising function; the alternative is a demo that fails at 8pm because a
teammate sent the other shape.
"""
from __future__ import annotations

from .. import clock, templates
from ..config import AUTO_DOC_CONFIDENCE, URGENT_HOURS
from ..errors import PayloadError
from ..mesh import Case


def _read_document(payload: dict) -> tuple[dict | None, float | None]:
    """Pull (fields, confidence) out of whichever shape the caller used."""
    doc = payload.get("doc") or payload.get("pod_document")
    confidence = payload.get("doc_confidence")
    if confidence is None:
        confidence = payload.get("confidence")

    fields: dict | None = None
    if isinstance(doc, dict):
        if isinstance(doc.get("extracted_fields"), dict):
            fields = dict(doc["extracted_fields"])
        else:
            # The document object IS the fields, as Person 3's dispute packet sends it.
            fields = {k: v for k, v in doc.items()
                      if k not in {"doc_type", "confidence", "extracted_fields"}}
        if confidence is None:
            confidence = doc.get("confidence")

    # Person 3 may also send the fields flat, beside pod_submitted.
    if fields is None and isinstance(payload.get("pod_fields"), dict):
        fields = dict(payload["pod_fields"])

    if payload.get("pod_submitted") and (fields is None or confidence is None):
        raise PayloadError(
            "pod_submitted was set, but no document fields or confidence came with it"
        )

    return fields, (float(confidence) if confidence is not None else None)


def _doc_amount(fields: dict) -> float | None:
    """Both spellings. sarvam_service returns `amount`; both specs say `amount_inr`."""
    for key in ("amount_inr", "amount"):
        if fields.get(key) is not None:
            try:
                return float(fields[key])
            except (TypeError, ValueError):
                return None
    return None


def gather(case: Case) -> str:
    """IntelligenceAgent: read the dispute, and the document if one came with it."""
    payload = case.req.payload or {}
    cb = case.ledger.chargeback

    txn_id = str(payload.get("txn_id") or payload.get("order_id") or cb.txn_id).lstrip("#")
    if txn_id not in {cb.txn_id, cb.order_id}:
        raise PayloadError(
            f"No dispute {txn_id!r} on this merchant; the open one is {cb.txn_id}"
        )

    fields, confidence = _read_document(payload)
    hours_left = round(clock.hours_until(cb.deadline_iso), 2)

    case.data = {
        "txn_id": cb.txn_id,
        "order_id": cb.order_id,
        "amount_held_inr": cb.amount_held_inr,
        "deadline_iso": cb.deadline_iso,
        "hours_left": hours_left,
    }

    if fields is None:
        # Step 1: nothing to check yet.
        case.data["evidence_status"] = cb.evidence_status
        case.data["hold_status"] = cb.hold_status
        return (
            f"Read dispute {cb.txn_id}: {cb.amount_held_inr} held, "
            f"{hours_left}h until the evidence deadline, no document yet"
        )

    # Step 2: a document arrived.
    case.data["document"] = {
        "order_id": str(fields.get("order_id") or "").lstrip("#").strip(),
        "amount_inr": _doc_amount(fields),
        "confidence": confidence,
        "source": payload.get("pod_source") or payload.get("source"),
    }
    doc = case.data["document"]
    return (
        f"Read dispute {cb.txn_id} and a proof of delivery: order "
        f"{doc['order_id'] or 'unreadable'}, amount {doc['amount_inr']}, "
        f"confidence {confidence}, {hours_left}h left"
    )


def assess(case: Case) -> str:
    """RiskPolicyAgent: deadline, then confidence, then whether the fields match."""
    cb = case.ledger.chargeback
    data = case.data
    hours_left = data["hours_left"]
    doc = data.get("document")

    # 1. The deadline, first, because it is the only failure a phone call can still fix.
    if hours_left <= 0:
        case.escalate(
            "DEADLINE_URGENT",
            f"The evidence deadline for dispute {cb.txn_id} has passed",
            urgency="URGENT", deadline_iso=cb.deadline_iso,
        )
        return f"The deadline passed {abs(hours_left)}h ago: only a person can act now"

    if doc is None and hours_left < URGENT_HOURS:
        case.escalate(
            "DEADLINE_URGENT",
            f"Only {hours_left}h left on dispute {cb.txn_id} and no proof of delivery yet",
            urgency="URGENT", deadline_iso=cb.deadline_iso,
        )
        return (
            f"No document and {hours_left}h left, inside the {URGENT_HOURS}h bar: "
            "a person should chase the merchant by phone"
        )

    if doc is None:
        return (
            f"{hours_left}h left, comfortably outside the {URGENT_HOURS}h bar: "
            "ask the merchant for the proof of delivery"
        )

    if hours_left < URGENT_HOURS:
        case.escalate(
            "DEADLINE_URGENT",
            f"Only {hours_left}h left on dispute {cb.txn_id}; a person should submit this",
            urgency="URGENT", deadline_iso=cb.deadline_iso,
        )
        return f"A document arrived, but with only {hours_left}h left a person should handle it"

    # 2. Confidence. Wrong evidence can lose the dispute outright, so the bar is high.
    confidence = doc["confidence"]
    if confidence is None or confidence < AUTO_DOC_CONFIDENCE:
        case.escalate(
            "LOW_DOC_CONFIDENCE",
            f"Proof of delivery unreadable (confidence {confidence})",
            deadline_iso=cb.deadline_iso,
        )
        return (
            f"Confidence {confidence} is below the {AUTO_DOC_CONFIDENCE} bar: "
            "not good enough to submit as evidence"
        )

    # 3. The fields. A clear document about the wrong order is still the wrong document.
    if doc["order_id"] != cb.order_id:
        case.escalate(
            "DOC_MISMATCH",
            f"Proof of delivery is for order {doc['order_id'] or 'unknown'}, "
            f"but the dispute is on order {cb.order_id}",
            deadline_iso=cb.deadline_iso,
        )
        return (
            f"Readable, but it is for order {doc['order_id'] or 'unknown'} "
            f"and the dispute is on {cb.order_id}"
        )

    if doc["amount_inr"] is not None and int(doc["amount_inr"]) != cb.amount_held_inr:
        case.escalate(
            "DOC_MISMATCH",
            f"Proof of delivery shows {doc['amount_inr']}, "
            f"but {cb.amount_held_inr} is held",
            deadline_iso=cb.deadline_iso,
        )
        return (
            f"Readable and the right order, but it shows {doc['amount_inr']} "
            f"against {cb.amount_held_inr} held"
        )

    return (
        f"Confidence {confidence} clears the {AUTO_DOC_CONFIDENCE} bar, order and amount "
        f"both match, {hours_left}h to spare: safe to submit"
    )


def resolve(case: Case) -> str:
    """ResolutionAgent: ask for the document, or confirm it is going in."""
    cb = case.ledger.chargeback
    data = case.data
    doc = data.get("document")

    if case.escalated:
        case.found = case.reason_text
        case.action_taken = "Nothing submitted; handed to a person"
        case.tried = ["Read the dispute from the ledger"]
        if doc is not None:
            case.tried.append(f"Checked the proof of delivery (confidence {doc['confidence']})")
        case.template_text = templates.render("CHARGEBACK_RESOLVE", data, "ESCALATED")
        return "Explained what is held, and handed the case to a person"

    if doc is None:
        # Step 1: the merchant has to do something before we can go further.
        case.status = "ACTION_REQUIRED"
        case.action_required = {
            "type": "UPLOAD_DOC",
            "doc_type": "pod",
            "deadline_iso": cb.deadline_iso,
            "hours_left": data["hours_left"],
        }
        case.found = (
            f"{cb.amount_held_inr} held on order {cb.order_id}, "
            f"{data['hours_left']}h to submit proof"
        )
        case.action_taken = "Asked the merchant for a proof of delivery"
        case.template_text = templates.render("CHARGEBACK_RESOLVE", data, "ACTION_REQUIRED")
        return f"Asked for the proof of delivery, with {data['hours_left']}h still to run"

    case.found = (
        f"Proof accepted for order {cb.order_id} (confidence {doc['confidence']}); "
        f"{cb.amount_held_inr} hold released"
    )
    case.action_taken = "Submitted the evidence and released the hold"
    case.template_text = templates.render("CHARGEBACK_RESOLVE", data, "RESOLVED")
    return "Confirmed the proof is going in and the held amount is coming back"


def apply(case: Case) -> str | None:
    """LedgerOpsAgent: the only stage in this service that releases held money."""
    if case.status != "RESOLVED":
        # Returning None rather than a note, so the trace honestly records that nothing
        # was touched on the way to asking for a document or escalating.
        return None

    cb = case.ledger.chargeback
    cb.evidence_status = "SUBMITTED"
    cb.hold_status = "RELEASED"

    case.data["evidence_status"] = cb.evidence_status
    case.data["hold_status"] = cb.hold_status
    # Always present, and said out loud in the demo: in real life the banks decide a
    # dispute, not this agent. We show the hold released so the flow can be seen end
    # to end, and we label it.
    case.data["simulated"] = True

    return (
        f"Submitted the evidence and released the {cb.amount_held_inr} hold "
        "(simulated: the banks decide the real outcome)"
    )
