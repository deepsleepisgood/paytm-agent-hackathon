"""In-memory merchant-side state for PAYTM_MERCH_8821 (Sharma Electronics)."""
from __future__ import annotations

import copy
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import dataset_loader as dl
import repository


def order_sheet() -> dict[str, Any]:
    """Merchant's own books for the settlement, from dataset/seed (merchant.json + settlement.json)."""
    d = dl.DATA
    s = d.settlement
    return {
        "mid": d.merchant["mid"],
        "merchant_name": d.merchant["name"],
        "gstin": d.merchant.get("gstin"),
        "settlement_date": s["settlement_date"],
        "expected_gross": s["gross"],
        "bank_credit_received": s["net_bank_credit"],
        "variance": s["variance"],
    }


class MerchantState:
    def __init__(self) -> None:
        self.a2a_events: list[dict[str, Any]] = []
        self.local_gst_itc_log: list[dict[str, Any]] = []
        self.fraud_alerts: list[dict[str, Any]] = []
        # PLAN.md step 5: verified outcomes learned this session (priors live in advisor.STRATEGY_PRIORS)
        self.strategy_memory: list[dict[str, Any]] = []
        # Khata entries created by resolved actions (refunds, releases, EDI pauses) on top of the settlement
        self.khata_entries: list[dict[str, Any]] = []
        # CONTRACT.md V2 proactive flows awaiting the merchant's 1-tap confirmation
        self.dispute_packets: dict[str, dict[str, Any]] = {}
        self.edi_offers: dict[str, dict[str, Any]] = {}
        self._loan_edi_status = "ACTIVE"  # last EDI status Paytm reported (EDI_PAUSED flips it)
        # payments.py: stuck UPI payments the buddy found and is watching (utr -> status, Paytm ticket)
        self.payment_watch: dict[str, dict[str, Any]] = {}
        self.session_id = f"SESS_{uuid.uuid4().hex[:8].upper()}"  # one per demo run; /reset starts a new one
        self._seq = 0

    @property
    def loan_edi_status(self) -> str:
        return self._loan_edi_status

    @loan_edi_status.setter
    def loan_edi_status(self, value: str) -> None:
        if value != self._loan_edi_status:
            repository.set_state("loan_edi_status", value)  # no-op unless USE_SUPABASE=true
        self._loan_edi_status = value

    def reset(self) -> None:
        self.__init__()
        repository.reset()  # restores the merchant schema too (no-op unless USE_SUPABASE=true)

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
        # Mirrored to merchant.a2a_events, which drives the console's Realtime feed.
        repository.log_event(type_, actor, summary, event["payload"], request_id, self.session_id)
        return event

    def add_gst_itc(self, entry: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Append an ITC entry unless the same (settlement_date, amount) is already logged."""
        key = (entry.get("settlement_date"), entry.get("amount"))
        for existing in self.local_gst_itc_log:
            if (existing.get("settlement_date"), existing.get("amount")) == key:
                return None
        self.local_gst_itc_log.append(entry)
        repository.add_gst_itc(entry)
        return entry

    @property
    def gst_itc_total(self) -> float:
        return float(sum(e.get("amount", 0) for e in self.local_gst_itc_log))


STATE = MerchantState()
