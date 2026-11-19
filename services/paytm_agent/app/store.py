"""All mutable state for this service, in one module.

State is in memory and dies with the process, which the contract accepts for the demo.
Keeping every store here, rather than scattering globals across the intent handlers,
buys two things:

  - `reset()` genuinely resets everything, so a test or a demo run starts clean;
  - the dispatch idempotency gate can protect *all* side effects, because it knows where
    they all are. A session counter hidden inside a handler would be mutated twice by a
    replayed request and silently trip the unknown-UTR limit one call early.

Every store created here at once, even the ones not used until a later stage, for that
second reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import clock, seed
from .seed import Ledger


@dataclass
class SessionState:
    """What we remember within one merchant conversation."""

    session_id: str
    started_at: str
    # Counts unknown-UTR *lookups*, not distinct UTR strings: a merchant reading the
    # same bogus reference three times is the same warning sign as three different ones.
    unknown_utr_count: int = 0
    # Used to spot a merchant raising the same issue twice without it being solved.
    intents_seen: list[str] = field(default_factory=list)


# --- the stores ------------------------------------------------------------------------
ledger: Ledger = seed.fresh()
summaries: list[dict] = []
tickets: dict[str, dict] = {}
sessions: dict[str, SessionState] = {}
# request_id -> the exact response envelope we returned the first time.
idempotency: dict[str, dict] = {}
# Fraud signals have nowhere to live in the frozen summary schema, so they are counted
# here for the metrics strip.
fraud_events: list[dict] = []

# V2 delta. Proactive alerts are not merchant calls, so they are kept apart from
# `summaries`: putting them in the call feed would inflate calls_total and make the
# auto-resolution rate describe something other than calls the merchant made.
alerts: dict[str, dict] = {}
# What the four sub-agents did on each call, keyed by summary_id. Kept beside the
# summaries rather than inside them so the call summary stays exactly the shape the
# contract froze, while the console can still show the reasoning behind a row.
traces: dict[str, list[dict]] = {}
# An EDI pause offer must outlive the alert that made it, because the merchant's
# confirmation arrives in a separate request carrying only its offer_id.
edi_offers: dict[str, dict] = {}

_counters: dict[str, int] = {}


def next_id(prefix: str) -> str:
    """Readable sequential ids: sum_001, tkt_001. Easier to follow on screen than UUIDs."""
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return f"{prefix}_{_counters[prefix]:03d}"


def next_code(prefix: str, width: int = 4) -> str:
    """Hyphenated, zero-padded ids: EDIOFFER-0001, KFS-ART-0001, as the contract writes them."""
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return f"{prefix}-{_counters[prefix]:0{width}d}"


def get_session(session_id: str) -> SessionState:
    if session_id not in sessions:
        sessions[session_id] = SessionState(session_id=session_id, started_at=clock.iso())
    return sessions[session_id]


def reset(chargeback_hours_left: float = seed.CHARGEBACK_DEFAULT_HOURS,
          break_settlement: bool = False) -> None:
    """Wipe everything and rebuild the ledger. The demo lever."""
    global ledger
    ledger = seed.fresh(chargeback_hours_left=chargeback_hours_left,
                        break_settlement=break_settlement)
    summaries.clear()
    tickets.clear()
    sessions.clear()
    idempotency.clear()
    fraud_events.clear()
    alerts.clear()
    edi_offers.clear()
    traces.clear()
    _counters.clear()
    # The V2 delta asks for this explicitly: a reset puts the EDI back to ACTIVE, so a
    # rehearsed demo can run the pause again.
    ledger.loan.status = "ACTIVE"


# --- derived counters the ledger view reports -------------------------------------------

def tickets_deflected() -> int:
    """Cases closed without a human ever being involved."""
    return sum(1 for s in summaries if s.get("outcome") == "RESOLVED_BY_AI")


def fraud_blocked() -> int:
    return len(fraud_events)
