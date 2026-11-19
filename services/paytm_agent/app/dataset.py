"""Loads the team's canonical Paytm-side data when it is there.

Only the NPCI UTR log is read, and only for payment lookups. Everything else stays in
seed.py as Python, with tests/test_canonical_alignment.py keeping the two in step.

The reason this one file is worth loading rather than transcribing: there are 6,541
payments in it, and a merchant can ask about any of them. With four references hardcoded
the agent answered "I cannot find this payment in your account" to almost every real
question — and that answer tells the merchant to withhold goods. Being confidently wrong
in that direction is the worst failure this service has, so the lookup reads the real
log.

If the file is absent — the service checked out on its own, or run from somewhere else —
the hardcoded references still work and the demo still runs.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

log = logging.getLogger("paytm_agent.dataset")

# services/paytm_agent/app/ -> repo root
PAYTM_DATA = Path(__file__).resolve().parents[3] / "data" / "paytm"
UTR_LOG = PAYTM_DATA / "npci_utr_log.csv"

# NPCI's status, as our lookup reports it. FAILED is a real outcome and not the same as
# NOT_FOUND: we know what happened to the money, which is the opposite of not finding it.
STATUS_MAP = {
    "SUCCESS": "SUCCESS_SETTLED",
    "PENDING": "PENDING",
    "FAILED": "FAILED",
    # The money reached the merchant and was sent back. Not a failure to find it, and
    # not a failure to pay: a reversal, which the merchant needs told plainly.
    "REVERSED": "REVERSED",
}

_cache: dict | None = None


def load_utrs() -> dict | None:
    """Every payment in the log, keyed by UTR. None when the log is not available.

    Parsed once and cached: /ledger/reset runs before every test, and re-reading 6,500
    rows each time took the suite from under a second to seven.
    """
    global _cache
    if _cache is not None:
        return _copies(_cache)
    if not UTR_LOG.exists():
        log.info("No canonical UTR log at %s; using the seeded references", UTR_LOG)
        return None

    from .seed import UpiTxn

    out: dict[str, UpiTxn] = {}
    try:
        with UTR_LOG.open(newline="") as fh:
            for row in csv.DictReader(fh):
                utr = (row.get("utr") or "").strip()
                status = STATUS_MAP.get((row.get("status") or "").strip().upper())
                if not utr or status is None:
                    continue
                try:
                    amount = int(float(row["amount"]))
                except (KeyError, TypeError, ValueError):
                    continue

                out[utr] = UpiTxn(
                    utr=utr,
                    amount_inr=amount,
                    payer_app=(row.get("payer_psp") or "").strip() or "Unknown",
                    lookup_status=status,
                    order_id=(row.get("order_id") or "").strip() or None,
                    received_at=(row.get("final_at") or row.get("initiated_at") or "").strip() or None,
                    resp_desc=(row.get("resp_desc") or "").strip() or None,
                )
    except OSError as exc:
        log.warning("Could not read %s (%s); using the seeded references", UTR_LOG, exc)
        return None

    log.info("Loaded %d payments from the canonical UTR log", len(out))
    _cache = out or None
    return _copies(_cache)


def _copies(cached: dict | None) -> dict | None:
    """Fresh objects every call.

    The cache only saves re-parsing the file. Handing out the cached objects themselves
    would mean a demo that marks a duplicate payment refunded leaves it refunded for
    good, and POST /ledger/reset would quietly stop resetting.
    """
    if not cached:
        return None
    from dataclasses import replace

    return {utr: replace(txn) for utr, txn in cached.items()}
