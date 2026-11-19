"""Supabase write-through for merchant_agent (owner of the `merchant` schema only).

`state.MerchantState` stays the hot copy every API response is built from, so no response
shape changes. Each change is mirrored into Postgres so the console's live A2A feed can be
driven by Supabase Realtime on `merchant.a2a_events`.

    USE_SUPABASE=true
    MERCHANT_DB_URL=postgresql://merchant_svc.<project-ref>:<password>@<pooler-host>:6543/postgres

* Off by default; without the flag, psycopg or the URL every call is a no-op.
* Writes go through ONE background thread, so they keep their order and never add database
  latency to a merchant reply (log() runs ~10 times per query). `flush()` waits for them;
  `reset()` drains the queue first so no stale event lands after a reset.
* Connection trouble logs one line and opens a 30 s circuit breaker; the service carries on in memory.
* Connects as `merchant_svc`, which has no privileges on the `paytm` schema: the two agents only
  ever talk over the A2A HTTP endpoints.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Optional

log = logging.getLogger("merchant_agent.repository")

try:  # optional dependency
    import psycopg
    from psycopg.types.json import Jsonb
    from psycopg_pool import ConnectionPool, PoolTimeout
    _OUTAGE = (psycopg.OperationalError, psycopg.InterfaceError, PoolTimeout, OSError, TimeoutError)
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

BREAKER_SECONDS = 30.0
MID = "PAYTM_MERCH_8821"


def _flag() -> bool:
    return os.getenv("USE_SUPABASE", "false").strip().lower() in ("1", "true", "yes", "on")


class _Repo:
    def __init__(self) -> None:
        self._pool = None
        self._lock = threading.Lock()
        self._down_until = 0.0
        self._warned_off = False
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="supabase-writer")

    def enabled(self) -> bool:
        if not _flag():
            return False
        if psycopg is None or not os.getenv("MERCHANT_DB_URL"):
            if not self._warned_off:
                log.warning("USE_SUPABASE=true but %s; falling back to in-memory state",
                            "psycopg is not installed" if psycopg is None else "MERCHANT_DB_URL is not set")
                self._warned_off = True
            return False
        return time.monotonic() >= self._down_until

    def _get_pool(self):
        with self._lock:
            if self._pool is None:
                self._pool = ConnectionPool(
                    os.environ["MERCHANT_DB_URL"], min_size=0, max_size=2, timeout=2, open=True,
                    kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": 3})
            return self._pool

    def _run(self, sql: str, args: tuple):
        if not self.enabled():
            return None
        try:
            with self._get_pool().connection() as conn:
                cur = conn.execute(sql, args)
                row = cur.fetchone() if cur.description else None
                return row[0] if row else None
        except Exception as exc:  # noqa: BLE001
            if psycopg is not None and isinstance(exc, (psycopg.errors.RaiseException,
                                                        psycopg.errors.InsufficientPrivilege,
                                                        psycopg.errors.UndefinedFunction,
                                                        psycopg.errors.UndefinedTable,
                                                        psycopg.errors.DataError,
                                                        psycopg.errors.IntegrityError)):
                log.error("Supabase rejected a merchant write: %s", str(exc).splitlines()[0][:200])
                return None
            if not isinstance(exc, _OUTAGE):
                log.error("Supabase write failed (%s: %s); in-memory state is unaffected",
                          type(exc).__name__, str(exc).splitlines()[0][:160] if str(exc) else "")
                return None
            self._down_until = time.monotonic() + BREAKER_SECONDS
            log.warning("Supabase unreachable (%s: %s); using in-memory state for %ds",
                        type(exc).__name__, str(exc).splitlines()[0][:160], BREAKER_SECONDS)
            return None

    def submit(self, sql: str, *args: Any) -> Optional[Future]:
        """Queue a write (in order). None when disabled, so callers pay nothing."""
        if not self.enabled():
            return None
        return self._writer.submit(self._run, sql, args)

    def flush(self, timeout: float = 5.0) -> None:
        if _flag():
            self._writer.submit(lambda: None).result(timeout=timeout)

    def close(self) -> None:
        try:
            self.flush()
        except Exception:  # noqa: BLE001 - interpreter shutdown / dead DB: nothing left to wait for
            pass
        with self._lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None


_repo = _Repo()
atexit.register(_repo.close)
enabled = _repo.enabled
flush = _repo.flush


def _json(v: Any):
    return Jsonb(v, dumps=lambda o: json.dumps(o, default=str, ensure_ascii=False)) if psycopg else None


# --- the merchant.* writes -------------------------------------------------------------
def log_event(type_: str, actor: str, summary: str, payload: dict | None, request_id: str | None,
              session_id: str | None) -> None:
    _repo.submit("select merchant.log_event(%s, %s, %s, %s, %s, %s, %s)",
                 type_, actor, summary, _json(payload or {}), request_id, session_id, MID)


def add_gst_itc(entry: dict) -> None:
    _repo.submit("select merchant.add_gst_itc(%s::date, %s::bigint, %s, %s)",
                 entry.get("settlement_date"), round(float(entry.get("amount") or 0)),
                 entry.get("basis") or entry.get("source"), entry.get("request_id"))


def record_strategy(record: dict) -> None:
    _repo.submit("select merchant.record_strategy(%s, %s, %s, %s, %s, %s, %s)",
                 record.get("intent"), f"{record.get('action')} (verified via {record.get('basis')})",
                 [str(record.get("option_id"))] if record.get("option_id") else [],
                 record.get("action"), record.get("paytm_status"), record.get("outcome") == "SUCCESS", None)


def add_fraud_alert(alert: dict) -> None:
    _repo.submit("insert into merchant.fraud_alerts (utr, payload) values (%s, %s)",
                 alert.get("utr_number"), _json(alert))


def set_state(key: str, value: str) -> None:
    _repo.submit("insert into merchant.agent_state (key, value) values (%s, %s) "
                 "on conflict (key) do update set value = excluded.value", key, value)


def reset() -> Optional[dict]:
    """Synchronous: queued writes land first, then merchant.reset_demo() runs."""
    fut = _repo.submit("select merchant.reset_demo()")
    try:
        return fut.result(timeout=5) if fut else None
    except Exception:  # noqa: BLE001
        log.warning("merchant.reset_demo did not finish in time; in-memory state was reset")
        return None
