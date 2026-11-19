"""The one entry point, and the only module that knows the order of side effects.

Every dispatch runs the same pipeline:

    idempotency gate -> consent -> merchant -> intent -> handler
                     -> fraud event -> summary -> ticket -> response -> cache

Two decisions worth knowing, because they are not obvious from the contract:

**Errors write nothing and are not cached.** A validation failure returns the error
envelope, writes no call summary, creates no ticket and is not remembered. So a request
rejected for a missing consent token can be retried, fixed, with the same `request_id`
and succeed. Caching it would strand Person 3 on a permanent error for a mistake they
had already corrected. It also keeps "every dispatch writes exactly one summary" true
of the summaries that exist, which is what the metrics are counted from.

**The gate sits above the handler, not inside it.** Everything with a side effect — the
summary, the ticket, the session's unknown-UTR counter, and any ledger mutation such as
releasing a chargeback hold — happens after the gate. A replayed `request_id` returns
the original bytes and touches none of it.
"""
from __future__ import annotations

import logging
import time

from . import clock, mesh, repository, store, templates
from .errors import PayloadError, error_body
from .escalation import create_ticket
from .intents import MODULES
from .mesh import Case
from .models import (
    INTENTS,
    OUTCOME_BY_STATUS,
    DispatchRequest,
    IntentResult,
    canonical_intent,
)

log = logging.getLogger("paytm_agent.dispatch")


def dispatch(req: DispatchRequest) -> tuple[dict, int]:
    """Returns (body, http_status)."""
    started = time.perf_counter()

    # --- 1. idempotency gate ------------------------------------------------------------
    cached = store.idempotency.get(req.request_id)
    if cached is not None:
        if cached.get("_request_fingerprint") != _fingerprint(req):
            # Same id, different content. The first answer still wins: re-running would
            # double-count metrics and could release a hold twice. Log it rather than
            # erroring, so a confused caller still gets a usable answer.
            log.warning("request_id %s replayed with a different payload", req.request_id)
        return _public(cached), 200

    # --- 2. consent ---------------------------------------------------------------------
    # Checked before anything is read: no consent, no look at the merchant's money.
    # With USE_SUPABASE every check (missing ones included) is logged to paytm.consent_checks.
    consent = repository.check_consent(req.mid, req.consent_token, req.request_id)
    if not (req.consent_token or "").strip():
        return error_body("CONSENT_MISSING", "consent_token is required"), 400
    if consent is not None and not consent.get("valid"):
        return error_body("DPDP_CONSENT_REQUIRED",
                          f"consent token is {str(consent.get('reason')).lower()}"), 403

    # --- 3. the merchant ----------------------------------------------------------------
    if req.mid != store.ledger.mid:
        return error_body("UNKNOWN_MID", f"No merchant {req.mid!r} in this service"), 404

    # --- 4. the intent ------------------------------------------------------------------
    # Normalised, because the same scenario has two names across the team.
    intent = canonical_intent(req.intent)
    if intent is None:
        return error_body(
            "UNKNOWN_INTENT",
            f"{req.intent!r} is not one of {list(INTENTS)}",
        ), 400

    module = MODULES.get(intent)
    if module is None:
        # Scaffolding while the intents are built one stage at a time. A test at stage 7
        # asserts every contract intent has a handler, so this cannot survive to the demo.
        return error_body("INTERNAL", f"{intent} is recognised but not implemented yet"), 501

    # --- 5. the session -----------------------------------------------------------------
    # Falls back to the request id so an agent that forgets session_id still works; it
    # just means each call is its own session and cross-call rules cannot fire.
    session = store.get_session(req.session_id or req.request_id)

    # --- 6. run the four sub-agents -----------------------------------------------------
    try:
        result, agent_trace = mesh.orchestrate(
            Case(req=req, ledger=store.ledger, session=session), module
        )
    except PayloadError as exc:
        # IntelligenceAgent could not read the request. There is no story to tell, so
        # the partial trace is dropped with the error.
        return error_body("BAD_PAYLOAD", str(exc)), 400

    session.intents_seen.append(intent)

    # --- 7. side effects, in order ------------------------------------------------------
    if result.fraud_event:
        store.fraud_events.append({**result.fraud_event, "at": clock.iso(),
                                   "session_id": session.session_id})

    summary_id = store.next_id("sum")

    ticket = None
    if result.status == "ESCALATED":
        ticket = create_ticket(result, req, store.ledger.merchant_name, summary_id)
        # The contract's ESCALATE_HUMAN data is {"ticket_id": ...}; for other intents
        # this is additive and lets the console link a summary straight to its ticket.
        result.data.setdefault("ticket_id", ticket["ticket_id"])

    duration_ms = int((time.perf_counter() - started) * 1000)
    summary = {
        "summary_id": summary_id,  # CONTRACT
        "request_id": req.request_id,  # CONTRACT
        "session_id": session.session_id,  # CONTRACT
        "created_at": clock.iso(),  # CONTRACT
        "duration_ms": duration_ms,  # CONTRACT
        "mid": req.mid,  # CONTRACT
        "merchant_name": store.ledger.merchant_name,  # CONTRACT
        "language_code": req.language_code,  # CONTRACT
        "merchant_said": req.merchant_said,  # CONTRACT
        # Canonical, so the console groups the same scenario under one name however
        # the caller spelled it.
        "intent": intent,  # CONTRACT
        "found": result.found,  # CONTRACT
        "action_taken": result.action_taken,  # CONTRACT
        "outcome": OUTCOME_BY_STATUS[result.status],  # CONTRACT
        "ticket_id": ticket["ticket_id"] if ticket else None,  # CONTRACT
    }
    store.summaries.append(summary)
    store.traces[summary_id] = agent_trace

    # --- 8. the response ----------------------------------------------------------------
    body = {
        "request_id": req.request_id,  # CONTRACT
        "status": result.status,  # CONTRACT
        # Echoed exactly as the caller sent it, so Person 3's own validation passes
        # whichever of the two names they chose.
        "intent": req.intent,  # CONTRACT
        # Additive: the name this service worked with, when it differed.
        **({"intent_canonical": intent} if intent != req.intent else {}),
        "data": result.data,  # CONTRACT
        # Composed by ResolutionAgent; the fallback covers an intent whose module does
        # not write one yet.
        "template_text": (
            result.template_text
            or templates.render(intent, result.data, result.status)
        ),  # CONTRACT
        # Which sub-agents collaborated on this request, and what each concluded.
        "agent_trace": agent_trace,
        "action_required": result.action_required,  # CONTRACT
        "escalation_ticket": ticket,  # CONTRACT
        "summary_id": summary_id,  # CONTRACT
        # Private bookkeeping, stripped before the body leaves this module.
        "_request_fingerprint": _fingerprint(req),
    }
    store.idempotency[req.request_id] = body
    # Mirror into Supabase (no-op unless USE_SUPABASE=true; never raises).
    repository.after_dispatch(req, intent, result, summary, agent_trace, ticket, store.ledger)
    return _public(body), 200


def _public(body: dict) -> dict:
    return {k: v for k, v in body.items() if not k.startswith("_")}


def _fingerprint(req: DispatchRequest) -> tuple:
    return (req.mid, req.intent, repr(sorted((req.payload or {}).items(), key=repr)))
