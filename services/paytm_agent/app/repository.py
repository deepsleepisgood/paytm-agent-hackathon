"""Supabase write-through for paytm_agent (owner of the `paytm` schema only).

The in-memory `store` stays the hot copy that every API response is built from, so the
CONTRACT.md shapes cannot change. This module mirrors each state change into Postgres
through the atomic functions in supabase/migrations (one RPC = one transaction), which
is what the console's Realtime feed and `/ledger/reset` restore read.

    USE_SUPABASE=true
    PAYTM_DB_URL=postgresql://paytm_svc.<project-ref>:<password>@<pooler-host>:6543/postgres

Rules:
  * Off by default. With USE_SUPABASE unset/false, or psycopg missing, or the URL missing,
    every function is a no-op that returns None and the service runs on memory alone.
  * Never raises into the request path for infrastructure trouble: a connection error
    logs one line, opens a 30 s circuit breaker and the service carries on in memory.
  * A *business* rejection from the database (e.g. EDI_PAUSE_NOT_ELIGIBLE) raises
    `DbRuleError` only where the caller asked for it (`pause_edi`); everywhere else it is
    logged as a divergence between memory and DB.
  * Connects as `paytm_svc`, which has no privileges on the `merchant` schema.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import threading
import time
from typing import Any

log = logging.getLogger("paytm_agent.repository")

try:  # optional dependency: the in-memory service must run without it
    import psycopg
    from psycopg.types.json import Jsonb
    from psycopg_pool import ConnectionPool, PoolTimeout
    _OUTAGE = (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout, OSError, TimeoutError)
except ImportError:  # pragma: no cover - exercised only where psycopg is absent
    psycopg = None  # type: ignore[assignment]

BREAKER_SECONDS = 30.0
_RULE = re.compile(r"^([A-Z_]+): ?(.*)$", re.S)


class DbRuleError(Exception):
    """The database refused a state change on business grounds (raised by a paytm.* function)."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _flag() -> bool:
    return os.getenv("USE_SUPABASE", "false").strip().lower() in ("1", "true", "yes", "on")


class _Repo:
    def __init__(self) -> None:
        self._pool = None
        self._lock = threading.Lock()
        self._down_until = 0.0
        self._warned_off = False

    # --- plumbing -------------------------------------------------------------------
    def enabled(self) -> bool:
        if not _flag():
            return False
        if psycopg is None or not os.getenv("PAYTM_DB_URL"):
            if not self._warned_off:
                log.warning("USE_SUPABASE=true but %s; falling back to in-memory state",
                            "psycopg is not installed" if psycopg is None else "PAYTM_DB_URL is not set")
                self._warned_off = True
            return False
        return time.monotonic() >= self._down_until

    def _get_pool(self):
        with self._lock:
            if self._pool is None:
                self._pool = ConnectionPool(
                    os.environ["PAYTM_DB_URL"], min_size=0, max_size=4, timeout=2, open=True,
                    # prepare_threshold=None: the Supabase pooler (transaction mode) cannot keep
                    # prepared statements. statement_timeout (3 s) is set on the role (migration 011).
                    kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": 3})
            return self._pool

    def _trip(self, exc: Exception) -> None:
        self._down_until = time.monotonic() + BREAKER_SECONDS
        log.warning("Supabase unreachable (%s: %s); using in-memory state for %ds",
                    type(exc).__name__, str(exc).splitlines()[0][:160], BREAKER_SECONDS)

    def call(self, sql: str, *args: Any, raise_rules: bool = False):
        """Run `select <fn>(...)`, return its single value. None when disabled or unreachable."""
        if not self.enabled():
            return None
        try:
            with self._get_pool().connection() as conn:
                row = conn.execute(sql, args).fetchone()
                return row[0] if row else None
        except Exception as exc:  # noqa: BLE001 - classified below
            if psycopg is not None and isinstance(exc, psycopg.errors.RaiseException):
                m = _RULE.match(exc.diag.message_primary or str(exc))
                code, detail = (m.group(1), m.group(2)) if m else ("DB_RULE", str(exc))
                if raise_rules:
                    raise DbRuleError(code, detail) from None
                log.warning("DB diverged from memory: %s: %s", code, detail)
                return None
            if psycopg is not None and isinstance(exc, (psycopg.errors.InsufficientPrivilege,
                                                        psycopg.errors.UndefinedFunction,
                                                        psycopg.errors.UndefinedTable)):
                log.error("Supabase schema/permission problem: %s", exc)  # config bug, not an outage
                return None
            if isinstance(exc, _OUTAGE):
                self._trip(exc)
            else:
                log.error("Supabase write failed (%s: %s); in-memory state is unaffected",
                          type(exc).__name__, str(exc).splitlines()[0][:160] if str(exc) else "")
            return None

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None


_repo = _Repo()
atexit.register(_repo.close)
enabled = _repo.enabled


def _jsonb(value):
    return Jsonb(value, dumps=lambda o: json.dumps(o, default=str, ensure_ascii=False)) if psycopg else None


# --- the paytm.* functions --------------------------------------------------------------
def check_consent(mid: str, token: str | None, request_id: str | None,
                  purpose: str = "A2A dispatch") -> dict | None:
    """{'valid', 'reason', 'consent_id', 'http_status'}; logged to paytm.consent_checks. None = not checked."""
    return _repo.call("select paytm.check_consent(%s, %s, %s, %s)", mid, token, purpose, request_id)


def verify_utr(mid: str, utr: str, request_id: str | None) -> dict | None:
    return _repo.call("select paytm.verify_utr(%s, %s, %s)", mid, utr, request_id)


def release_chargeback(case_ref: str, pod_ref: str, request_id: str | None) -> dict | None:
    return _repo.call("select paytm.release_chargeback(%s, %s, %s)", case_ref, pod_ref, request_id)


def execute_refund_by_utr(utr: str, amount: int, reason: str, approver: str | None,
                          request_id: str | None) -> dict | None:
    return _repo.call(
        "select paytm.execute_refund((select txn_id from paytm.npci_utr_log where utr = %s),"
        " %s, %s, %s, null, %s)", utr, amount, reason, approver, request_id)


def pause_edi(mid: str, pause_days: int, kfs_clause: str, offer_id: str | None,
              consent_token: str | None, request_id: str | None = None) -> dict | None:
    """Raises DbRuleError (e.g. EDI_PAUSE_NOT_ELIGIBLE, CONSENT_INVALID) so the caller can 409/403."""
    # Checked in its own transaction first: inside pause_edi a rejection rolls back, and the
    # consent_checks row recording the refusal would be lost with it.
    consent = check_consent(mid, consent_token, request_id, purpose="EDI pause (KFS 4.2)")
    if consent is not None and not consent.get("valid"):
        raise DbRuleError("CONSENT_INVALID", str(consent.get("reason")))
    return _repo.call(
        "select paytm.pause_edi((select loan_id from paytm.loan_book where mid = %s), %s, %s, %s, %s, %s)",
        mid, pause_days, kfs_clause, offer_id, consent_token, request_id, raise_rules=True)


def create_l2_ticket(mid: str, intent: str, summary: str, diagnostics: dict) -> dict | None:
    return _repo.call("select paytm.create_l2_ticket(%s, %s, %s, %s)", mid, intent, summary,
                      _jsonb(diagnostics))


def record_outcome(mid: str, intent: str, request_id: str | None, option_chosen: str | None,
                   outcome: str, success: bool, money_inr: int = 0) -> dict | None:
    return _repo.call("select paytm.record_outcome(%s, %s, %s, %s, %s, %s, %s)",
                      mid, intent, request_id, option_chosen, outcome, success, money_inr)


def log_agent_trace(mid: str, request_id: str | None, intent: str, steps: list[dict]) -> int | None:
    return _repo.call("select paytm.log_agent_trace(%s, %s, %s, %s)", mid, request_id, intent,
                      _jsonb(steps))


def reset(chargeback_hours_left: float = 48.0) -> dict | None:
    return _repo.call("select paytm.reset_demo(%s::numeric)", chargeback_hours_left)


# --- one call from dispatch -------------------------------------------------------------
def after_dispatch(req, intent: str, result, summary: dict, agent_trace: list[dict],
                   ticket: dict | None, ledger) -> None:
    """Mirror one finished dispatch into Postgres. Never raises; a no-op when disabled."""
    if not enabled():
        return
    try:
        data = result.data or {}
        money = 0
        if intent == "UTR_VERIFY" and data.get("utr"):
            verify_utr(req.mid, str(data["utr"]), req.request_id)
        elif intent == "CHARGEBACK_RESOLVE" and data.get("hold_status") == "RELEASED":
            cb = ledger.chargeback
            if release_chargeback(cb.order_id, cb.order_id, req.request_id):
                money = int(cb.amount_held_inr)
        elif data.get("refund_status") == "PROCESSED" and isinstance(data.get("refund"), dict):
            r = data["refund"]
            execute_refund_by_utr(str(r.get("utr")), int(r.get("amount_inr") or 0),
                                  "duplicate payment", "AUTO", req.request_id)
        if ticket:
            create_l2_ticket(req.mid, intent, ticket.get("reason_text") or summary.get("found") or intent,
                             {"service_ticket_id": ticket["ticket_id"], "summary_id": summary["summary_id"],
                              "reason_code": ticket.get("reason_code"), "urgency": ticket.get("urgency")})
        record_outcome(req.mid, intent, req.request_id, summary.get("action_taken"), summary["outcome"],
                       result.status == "RESOLVED", money)
        log_agent_trace(req.mid, req.request_id, intent, agent_trace)
    except Exception:  # noqa: BLE001 - the mirror must never break a dispatch
        log.exception("Supabase write-through failed for %s; in-memory state is unaffected", req.request_id)
