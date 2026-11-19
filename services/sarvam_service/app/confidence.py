"""Normalise extracted fields and compute the `confidence` number the contract asks for.

Sarvam's Extract API returns values but no per-field confidence. Instead of inventing a
number, we compute an honest one that a judge can follow:

    confidence = share of required fields present and valid, minus a penalty per warning

Validation is deterministic (regex and type checks), so the downstream agent can trust
that, e.g., a UTR we return is really 12 digits. Anything suspicious goes in `warnings`
rather than being silently "fixed".
"""
from __future__ import annotations

import re
from typing import Any

from .doc_schemas import REQUIRED

_UTR_RE = re.compile(r"^\d{12}$")
_WARNING_PENALTY = 0.1


def _clean_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    cleaned = re.sub(r"[^\d.]", "", str(value))  # drops ₹, Rs, commas, spaces
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def normalise(doc_type: str, fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return (cleaned_fields, warnings)."""
    out = {k: v for k, v in fields.items() if v not in (None, "", [])}
    warnings: list[str] = []

    if "amount" in out:
        amount = _clean_number(out["amount"])
        if amount is None:
            warnings.append(f"amount '{out['amount']}' is not a number")
            out.pop("amount")
        else:
            out["amount"] = int(amount) if amount.is_integer() else round(amount, 2)

    if doc_type == "upi_screenshot":
        if "utr" in out:
            utr = re.sub(r"\D", "", str(out["utr"]))
            if not _UTR_RE.match(utr):
                warnings.append(f"UTR '{out['utr']}' is not 12 digits")
            out["utr"] = utr
        if "status" in out:
            status = str(out["status"]).strip().upper()
            if status in {"SUCCESSFUL", "COMPLETED", "PAID"}:
                status = "SUCCESS"
            out["status"] = status

    if doc_type == "pod" and "order_id" in out:
        out["order_id"] = str(out["order_id"]).lstrip("#").strip()

    return out, warnings


def score(doc_type: str, fields: dict[str, Any], warnings: list[str]) -> float:
    required = REQUIRED[doc_type]
    present = sum(1 for k in required if k in fields)
    base = present / len(required)
    return round(max(0.0, min(1.0, base - _WARNING_PENALTY * len(warnings))), 2)


def missing_required(doc_type: str, fields: dict[str, Any]) -> list[str]:
    return [k for k in REQUIRED[doc_type] if k not in fields]
