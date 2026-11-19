"""The only place this service reads the system clock.

Why bother: deadline_iso, hours_left, URGENT_HOURS, duration_ms and
avg_resolution_ms_human all depend on "now". If five modules call datetime.now()
directly, the chargeback deadline tests become timing-dependent and the "6 hours left"
case can only be tested by actually sleeping. With one indirection a test can freeze
time and assert exact numbers.

Everything is timezone-aware UTC. Naive datetimes are a source of silent one-off bugs
when a deadline is compared against a stored ISO string.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_frozen: datetime | None = None


def now() -> datetime:
    """Current time, or the frozen time if a test has pinned it."""
    return _frozen if _frozen is not None else datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    """ISO-8601 string for a datetime, defaulting to now."""
    return (dt if dt is not None else now()).isoformat()


def hours_until(deadline_iso: str) -> float:
    """Hours remaining until an ISO deadline. Negative once it has passed.

    Always computed, never stored: a stored hours_left goes stale between chargeback
    step 1 and step 2 and would make the deadline tests pass for the wrong reason.
    """
    deadline = datetime.fromisoformat(deadline_iso)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return (deadline - now()).total_seconds() / 3600.0


def plus_hours(hours: float) -> datetime:
    return now() + timedelta(hours=hours)


# --- test helpers ----------------------------------------------------------------------

def freeze(dt: datetime) -> None:
    global _frozen
    _frozen = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def unfreeze() -> None:
    global _frozen
    _frozen = None
