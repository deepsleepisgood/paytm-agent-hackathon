"""CONTRACT.md V2 proactive flows (+ PLAN.md's MANDATE_FAILED alert).

The frontend simulates Paytm's webhook by calling POST /merchant/proactive-shield; 8003 then fetches
the alert from 8002 (/a2a/proactive-alert) and acts on it with consented merchant-side connectors:
  CHARGEBACK_INCOMING  -> pull the signed PoD from SHIPROCKET_SYNC, extract it (8001), prepare a
                          dispute packet and ask for a 1-tap sign-off. Nothing goes to Paytm until
                          POST /merchant/confirm-dispute.
  CASHFLOW_EDI_SWITCH  -> read tomorrow's stock payable from VYAPAR_POS_SYNC, detect the gap against
                          the projected payout and offer the KFS 2-day EDI pause; executed only on
                          POST /merchant/confirm-edi-pause.
  MANDATE_FAILED       -> diagnose friction vs default and send the 1-tap UPI link (non-binding).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

import advisor
import dataset_loader as dl
import pipeline
import upstream
from pipeline import ACTOR_MERCHANT, ACTOR_PAYTM
from schemas import ConfirmDisputeRequest, ConfirmEdiPauseRequest, ProactiveRequest, Slots
from state import STATE

# 8003 scenario -> (8002 trigger_type, intent used in responses/events)
SCENARIOS: dict[str, tuple[str, str]] = {
    "CHARGEBACK_INCOMING": ("CHARGEBACK_INCOMING", "CHARGEBACK_RESOLVE"),
    "CASHFLOW_EDI_SWITCH": ("HIGH_REFUND_CASHFLOW", "CASHFLOW_EDI_SWITCH"),
    "MANDATE_FAILED": ("MANDATE_FAILED_ALERT", "MANDATE_TROUBLESHOOT"),
}
_PRIVATE = ("insight", "evaluation", "cashflow")


def _public(rec: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    return {k: v for k, v in rec.items() if k not in _PRIVATE} if rec else None


def _block(scenario: str, alert: Optional[dict] = None, packet: Optional[dict] = None, cashflow: Optional[dict] = None,
           offer: Optional[dict] = None, awaiting: Optional[str] = None) -> dict[str, Any]:
    return {"scenario": scenario, "alert": alert, "dispute_packet": _public(packet), "cashflow": cashflow,
            "edi_pause_offer": _public(offer), "awaiting_confirmation": awaiting}


async def shield(req: ProactiveRequest) -> dict[str, Any]:
    request_id = pipeline.new_request_id()
    token = pipeline.require_consent(req.consent_granted, req.mid, request_id, channel=f"proactive:{req.scenario}")
    trigger, intent = SCENARIOS[req.scenario]
    alert, src = await upstream.proactive_alert(req.mid, trigger)
    STATE.log("PROACTIVE_ALERT_RECEIVED", ACTOR_PAYTM,
              f"Paytm alert {alert.get('alert_id', '')}: {trigger}" + (" [mock]" if src == "mock" else ""),
              {**alert, "_source": src}, request_id)
    args = (req, request_id, token, intent, alert, src)
    if req.scenario == "CHARGEBACK_INCOMING":
        return await _chargeback(*args)
    if req.scenario == "CASHFLOW_EDI_SWITCH":
        return await _cashflow(req.mid, request_id, token, alert, src, intent_source="proactive")
    return await _mandate(*args)


async def cashflow_from_query(mid: str, request_id: str, token: str, *, intent_source: str, merchant_text: str,
                              transcript: Optional[str] = None, transcript_source: Optional[str] = None) -> dict[str, Any]:
    """The merchant *asked* to pause the EDI ("stock ke paise kam hain, EDI ruk sakti hai?").
    A KFS pause needs an explicit consent artifact, so this makes the same offer as the proactive flow
    (eligibility from 8002) and waits for /merchant/confirm-edi-pause, rather than pausing on a question."""
    trigger = SCENARIOS["CASHFLOW_EDI_SWITCH"][0]
    STATE.log("MERCHANT_TO_PAYTM", ACTOR_MERCHANT, f"KFS EDI-pause eligibility check → Paytm ({trigger})",
              {"mid": mid, "trigger_type": trigger}, request_id)
    alert, src = await upstream.proactive_alert(mid, trigger)
    STATE.log("PAYTM_TO_MERCHANT", ACTOR_PAYTM, f"Eligibility ← Paytm: {alert.get('status')}" + (" [mock]" if src == "mock" else ""),
              {**alert, "_source": src}, request_id)
    return await _cashflow(mid, request_id, token, alert, src, intent_source=intent_source, merchant_text=merchant_text,
                           transcript=transcript, transcript_source=transcript_source)


async def _chargeback(req, request_id, token, intent, alert, src) -> dict[str, Any]:
    data = alert.get("data") or {}
    oid = dl.digits(data.get("order_id") or data.get("txn_id")) or (dl.DATA.chargeback() or {}).get("order_id", "9981")
    conn = dl.DATA.connector("SHIPROCKET_SYNC")
    packet, extract = None, None
    if conn is not None:
        path = dl.DATA.test_file(str(conn.get("pod_file") or f"pod_{oid}.png")) or dl.DATA.test_file(f"pod_{oid}.png")
        STATE.log("CONNECTOR_PULL", ACTOR_MERCHANT, f"Pulled signed PoD for #{oid} from SHIPROCKET_SYNC",
                  {"connector": "SHIPROCKET_SYNC", "consent": "GRANTED", "order_id": oid,
                   "document": path.name if path else f"pod_{oid}.png (8001 sample connector)"}, request_id)
        if path is not None:
            extract, xsrc = await upstream.doc_extract(path.read_bytes(), path.name, "image/png", "pod")
        else:  # Person 1 serves the Shiprocket PoD itself: /doc-extract use_sample_connector=true
            extract, xsrc = await upstream.doc_extract_sample("pod")
            if extract is None:
                extract, xsrc = upstream.mock_doc_extract("pod", f"pod_{oid}.png"), "mock"
        extract = {**extract, "_source": xsrc}
        STATE.log("DOC_EXTRACTED", ACTOR_MERCHANT, f"Proof of Delivery read (confidence {extract.get('confidence', 'n/a')})"
                  + (" [mock]" if xsrc == "mock" else ""), extract, request_id)
        packet = {"packet_id": f"DISPUTE-{oid}", "txn_id": str(data.get("txn_id") or oid), "order_id": oid,
                  "amount": data.get("amount"), "pod_source": "SHIPROCKET_SYNC",
                  "pod_fields": extract.get("extracted_fields") or {}, "doc_confidence": extract.get("confidence"),
                  "status": "READY_FOR_SIGNOFF", "alert_id": alert.get("alert_id")}
        STATE.log("DISPUTE_PACKET_READY", ACTOR_MERCHANT, f"Dispute packet {packet['packet_id']} ready for 1-tap sign-off",
                  packet, request_id)
    awaiting = "CONFIRM_DISPUTE" if packet else None
    result = await pipeline.run(
        request_id=request_id, mid=req.mid, consent_token=token, intent=intent, intent_source="proactive",
        slots=Slots(order_id=oid, amount=dl.num(data.get("amount"))), merchant_text=None,
        preset_response=(alert, src), doc_extract=extract,
        context={"pod_ready": packet is not None, "awaiting_confirmation": awaiting},
    )
    if packet:
        STATE.dispute_packets[packet["packet_id"]] = {**packet, "insight": result["historical_insight"],
                                                     "evaluation": result["intervention_evaluation"]}
        result["pending_action"] = {"type": "CONFIRM_DISPUTE", "packet_id": packet["packet_id"],
                                    "endpoint": "/merchant/confirm-dispute",
                                    "message": "Merchant 1-tap sign-off to submit the dispute with PoD"}
    result["proactive"] = _block(req.scenario, alert, packet, awaiting=awaiting)
    return result


async def _cashflow(mid: str, request_id: str, token: str, alert: dict[str, Any], src: str, *, intent_source: str,
                    merchant_text: Optional[str] = None, transcript: Optional[str] = None,
                    transcript_source: Optional[str] = None) -> dict[str, Any]:
    intent = "CASHFLOW_EDI_SWITCH"
    data = alert.get("data") or {}
    gap = advisor.cashflow_gap({"alert_data": data})
    if dl.DATA.connector("VYAPAR_POS_SYNC"):
        STATE.log("CONNECTOR_PULL", ACTOR_MERCHANT,
                  f"Read tomorrow's stock payable ₹{dl._inr_commas(gap['tomorrow_stock_due'])} from VYAPAR_POS_SYNC",
                  {"connector": "VYAPAR_POS_SYNC", "consent": "GRANTED", "stock_payable_tomorrow": gap["tomorrow_stock_due"]},
                  request_id)
    if gap["shortfall"] > 0:
        STATE.log("CASHFLOW_GAP_DETECTED", ACTOR_MERCHANT,
                  f"Payout ₹{dl._inr_commas(gap['projected_net_payout'])} < stock due "
                  f"₹{dl._inr_commas(gap['tomorrow_stock_due'])} (gap ₹{dl._inr_commas(gap['shortfall'])})", gap, request_id)
    offer = dict(data.get("edi_pause_offer") or {})
    ctx = {"alert_data": data, "cashflow": gap}
    insight = advisor.diagnose(intent, Slots(), None, ctx)
    evaluation = advisor.evaluate(intent, insight, Slots(), ctx)
    chosen = evaluation["selected_intervention"]["action"] == "KFS_EDI_PAUSE_2D"
    make_offer = bool(offer.get("offer_id")) and bool(offer.get("eligible")) and gap["shortfall"] > 0 and chosen
    awaiting = "CONFIRM_EDI_PAUSE" if make_offer else None
    result = await pipeline.run(
        request_id=request_id, mid=mid, consent_token=token, intent=intent, intent_source=intent_source,
        slots=Slots(), merchant_text=merchant_text, preset_response=(alert, src), insight=insight, evaluation=evaluation,
        context={**ctx, "awaiting_confirmation": awaiting}, transcript=transcript, transcript_source=transcript_source,
    )
    stored = None
    if make_offer:
        stored = {**offer, "status": "OFFERED", "request_id": request_id, "insight": insight, "evaluation": evaluation,
                  "cashflow": gap}
        STATE.edi_offers[offer["offer_id"]] = stored
        STATE.log("EDI_PAUSE_OFFERED", ACTOR_MERCHANT,
                  f"Offered {offer.get('nbfc')} EDI pause for {offer.get('pause_days')} days (KFS clause {offer.get('kfs_clause')})",
                  _public(stored), request_id)
        result["pending_action"] = {"type": "CONFIRM_EDI_PAUSE", "offer_id": offer["offer_id"],
                                    "pause_days": offer.get("pause_days"), "endpoint": "/merchant/confirm-edi-pause",
                                    "message": "Merchant consent needed to pause the EDI"}
    else:
        result["pending_action"] = None
    result["proactive"] = _block("CASHFLOW_EDI_SWITCH", alert, cashflow=gap, offer=stored or offer or None, awaiting=awaiting)
    return result


async def _mandate(req, request_id, token, intent, alert, src) -> dict[str, Any]:
    data = alert.get("data") or {}
    result = await pipeline.run(
        request_id=request_id, mid=req.mid, consent_token=token, intent=intent, intent_source="proactive",
        slots=Slots(amount=dl.num(data.get("edi_amount"))), merchant_text=None,
        extra_payload={"alert_id": alert.get("alert_id"), "trigger_type": alert.get("trigger_type")},
        context={"alert_data": data},
    )
    result["proactive"] = _block(req.scenario, alert)
    return result


def _not_found(error: str, what: str, value: str) -> HTTPException:
    return HTTPException(404, detail={"error": error, "message": f"No {what} '{value}'. Call /merchant/proactive-shield first.",
                                      "message_hi": "Yeh offer/packet nahi mila, pehle alert dobara chalaiye."})


async def confirm_dispute(req: ConfirmDisputeRequest) -> dict[str, Any]:
    request_id = pipeline.new_request_id()
    token = pipeline.require_consent(req.consent_granted, req.mid, request_id, channel="proactive:confirm-dispute")
    packet = STATE.dispute_packets.get(req.packet_id)
    if packet is None:
        raise _not_found("PACKET_NOT_FOUND", "dispute packet", req.packet_id)
    STATE.log("MERCHANT_SIGNOFF", ACTOR_MERCHANT, f"Merchant signed off dispute {req.packet_id} (1-tap)",
              {"packet_id": req.packet_id, "consent_token": token}, request_id)
    extra = {"order_id": packet["order_id"], "txn_id": packet["txn_id"], "pod_submitted": True,
             "pod_document": packet["pod_fields"], "pod_source": "SHIPROCKET_SYNC", "doc_confidence": packet["doc_confidence"]}
    result = await pipeline.run(
        request_id=request_id, mid=req.mid, consent_token=token, intent="CHARGEBACK_RESOLVE", intent_source="proactive",
        slots=Slots(order_id=packet["order_id"], amount=dl.num(packet.get("amount"))), merchant_text=None,
        extra_payload=extra, insight=packet["insight"], evaluation=packet["evaluation"],
    )
    packet.update(status="SUBMITTED", paytm_status=result["paytm_response"].get("status"), submit_request_id=request_id)
    result["proactive"] = _block("CHARGEBACK_INCOMING", packet=packet)
    return result


async def confirm_edi_pause(req: ConfirmEdiPauseRequest) -> dict[str, Any]:
    request_id = pipeline.new_request_id()
    token = pipeline.require_consent(req.consent_granted, req.mid, request_id, channel="proactive:confirm-edi-pause")
    offer = STATE.edi_offers.get(req.offer_id)
    if offer is None:
        raise _not_found("OFFER_NOT_FOUND", "EDI-pause offer", req.offer_id)
    max_days = int(offer.get("pause_days") or (dl.DATA.history.get("kfs") or {}).get("max_pause_days", 2))
    days = req.pause_days or max_days
    if days > max_days:
        raise HTTPException(409, detail={"error": "EDI_PAUSE_NOT_ELIGIBLE",
                                         "message": f"KFS clause {offer.get('kfs_clause', '4.2')} allows at most {max_days} days",
                                         "message_hi": f"KFS ke hisaab se EDI zyada se zyada {max_days} din hi ruk sakti hai."})
    STATE.log("MERCHANT_SIGNOFF", ACTOR_MERCHANT, f"Merchant consented to pause EDI for {days} days ({req.offer_id})",
              {"offer_id": req.offer_id, "pause_days": days, "consent_token": token}, request_id)
    upstream.remember_offer(offer)  # so the offline mock can execute an offer that a live 8002 made

    async def call(envelope: dict[str, Any]) -> tuple[dict[str, Any], str]:
        return await upstream.execute_edi_pause({"mid": req.mid, "consent_token": envelope["consent_token"],
                                                 "pause_days": days, "offer_id": req.offer_id})

    try:
        result = await pipeline.run(
            request_id=request_id, mid=req.mid, consent_token=token, intent="CASHFLOW_EDI_SWITCH",
            intent_source="proactive", slots=Slots(), merchant_text=None,
            extra_payload={"offer_id": req.offer_id, "pause_days": days}, call=call,
            insight=offer["insight"], evaluation=offer["evaluation"], context={"cashflow": offer.get("cashflow")},
        )
    except upstream.UpstreamRejected as rej:
        STATE.log("PAYTM_REJECTED", ACTOR_PAYTM, f"Paytm refused the EDI pause ({rej.status_code})",
                  {"status_code": rej.status_code, "detail": rej.detail}, request_id)
        raise
    resp = result["paytm_response"]
    if str(resp.get("status")).upper() == "EDI_PAUSED":
        d = resp.get("data") or {}
        STATE.log("EDI_PAUSED", ACTOR_PAYTM, f"EDI {d.get('loan_edi_status')} — resumes {d.get('resume_date')}", d, request_id)
        offer["status"] = "ACCEPTED"
    result["proactive"] = _block("CASHFLOW_EDI_SWITCH", cashflow=offer.get("cashflow"), offer=offer)
    return result
