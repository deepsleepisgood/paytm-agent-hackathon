"""In-memory merchant-side state for PAYTM_MERCH_8821 (Sharma Electronics)."""
from __future__ import annotations

import copy
import time
from datetime import datetime, timezone
from typing import Any, Optional

MERCHANT_ORDER_SHEET: dict[str, Any] = {
    "mid": "PAYTM_MERCH_8821",
    "merchant_name": "Sharma Electronics",
    "settlement_date": "2026-11-18",
    "expected_gross": 100000,
    "bank_credit_received": 95840,
    "variance": 4160,
}


class MerchantState:
    def __init__(self) -> None:
        self.a2a_events: list[dict[str, Any]] = []
        self.local_gst_itc_log: list[dict[str, Any]] = []
        self.fraud_alerts: list[dict[str, Any]] = []
        self._seq = 0

    def reset(self) -> None:
        self.__init__()

    def log(
        self,
        type_: str,
        actor: str,
        summary: str,
        payload: Optional[dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> dict[str, Any]:
        self._seq += 1
        now = time.time()
        event = {
            "seq": self._seq,
            "ts": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "unix": now,
            "type": type_,
            "actor": actor,
            "request_id": request_id,
            "summary": summary,
            "payload": copy.deepcopy(payload or {}),
        }
        self.a2a_events.append(event)
        return event

    def add_gst_itc(self, entry: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Append an ITC entry unless the same (settlement_date, amount) is already logged."""
        key = (entry.get("settlement_date"), entry.get("amount"))
        for existing in self.local_gst_itc_log:
            if (existing.get("settlement_date"), existing.get("amount")) == key:
                return None
        self.local_gst_itc_log.append(entry)
        return entry

    @property
    def gst_itc_total(self) -> float:
        return float(sum(e.get("amount", 0) for e in self.local_gst_itc_log))


STATE = MerchantState()
