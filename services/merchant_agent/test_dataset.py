"""Dataset integration tests.

1. Loader: two fixture datasets with *different plausible schemas* (the teammate's final field
   names aren't known yet) must normalise to the same values; broken files fall back per file.
2. Wiring: dataset values must drive mock Paytm answers, replies, routing, ITC entries, /presets.
3. Person 1 (8001) compatibility, using the exact response shapes in services/sarvam_service.
4. The real repo-root dataset/ (skipped until a teammate adds it): every file parses, the
   settlement adds up, utterances route, golden paths and test files behave as expected.
"""
import asyncio
import json
import warnings
from pathlib import Path

import httpx
import pytest

import router
import upstream
from conftest import NO_DATASET, REAL_DATASET, ask, upload, use_dataset

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # content is irrelevant offline; names drive the mock

# ----------------------------------------------------------------------------- fixture datasets

VARIANT_A = {  # tidy snake_case, lists of records
    "seed/merchant.json": {"mid": "PAYTM_MERCH_8821", "name": "Sharma Electronics", "gstin": "07ABCDE1234F1Z5",
                           "soundbox": {"device_id": "SBX-8821-01", "model": "Soundbox 5.0"}},
    "seed/settlement.json": {
        "settlement_date": "2026-11-18",
        "gross_mix": {"credit_card": 50000, "wallet_upi_above_2k": 25000, "bank_upi": 25000},
        "net_bank_credit": 95840,
        "deductions": [
            {"code": "MDR_FEE", "amount": 1450},
            {"code": "GST_ON_MDR", "amount": 261, "itc_eligible": True},
            {"code": "CUSTOMER_REFUND", "amount": 1500, "order_id": "#4412"},
            {"code": "SOUNDBOX_RENTAL", "amount": 149},
            {"code": "CHARGEBACK_HOLD", "amount": 800, "order_id": "#9981", "txn_id": "#9981", "status": "HELD"},
        ],
        "checks": {"deductions_sum": 4160},
    },
    "seed/transactions.json": {"transactions": [
        {"utr": "632184920111", "amount": 1250, "payer_app": "GPay", "status": "SUCCESS"},
        {"utr": "632184920999", "amount": 2400, "payer_app": "PhonePe", "status": "PENDING"},
        {"utr": "632184920222", "amount": 999, "payer_app": "Paytm", "status": "SUCCESS"},
        {"utr": "632184920333", "amount": 3100, "payer_app": "BHIM", "status": "FAILED"},
    ]},
    "seed/refunds_orders.json": {
        "refunds": [{"order_id": "4412", "amount": 1500, "status": "PROCESSED"}],
        "chargebacks": [{"order_id": "9981", "txn_id": "9981", "amount": 800, "status": "HELD", "pod_due_in_hours": 48}],
        "policy": {"autonomous_refund_limit": 3000},
    },
    "seed/loan.json": {"loan": {"edi_per_day": 500, "outstanding_balance": 42000, "next_deduction": "2026-11-20"}},
    "seed/fee_rules.json": {"mdr_rates": [{"instrument": "credit_card", "rate": 0.02},
                                          {"instrument": "wallet_on_upi_above_2000", "rate": 0.011},
                                          {"instrument": "bank_upi", "rate": 0}], "gst_rate": 0.18},
    "seed/initial_state.json": {"chargebacks": {"9981": {"order_id": "9981", "status": "HELD"}},
                                "counters": {"frauds_blocked": 0, "tickets_deflected": 0}},
    "intents/utterances.json": {"intents": {
        "SETTLEMENT_RECONCILE": [{"text": "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?", "preset": True},
                                 {"text": "paise kam kyun aaye"}],
        "CHARGEBACK_RESOLVE": [{"text": "Bhaiya mera paisa atka hua hai", "preset": True}],
        "UTR_VERIFY": [{"text": "UTR 632184920111 ka payment aaya kya?"}],
        "REFUND_MANAGE": [{"text": "order 4412 ka refund hua kya"}],
        "FEE_GST_LOAN": [{"text": "GST ka ITC kitna milega"}],
        "ESCALATE_HUMAN": [{"text": "soundbox bol nahi raha", "preset": True}],
    }},
    "golden/golden_paths.json": {"steps": [
        {"name": "settlement", "input": {"text": "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?"},
         "expected": {"intent": "SETTLEMENT_RECONCILE", "gst_itc_logged": 261}},
        {"name": "pod", "input": {"file": "test_files/pod_9981.png", "doc_type": "pod"},
         "expected": {"intent": "CHARGEBACK_RESOLVE", "status": "RELEASED"}},
        {"name": "fake", "input": {"file": "test_files/fake_upi.png", "doc_type": "upi_screenshot"},
         "expected": {"intent": "UTR_VERIFY", "status": "NOT_FOUND_SUSPECTED_FAKE", "fraud_alert": True}},
    ]},
    "seed/merchant_history.json": {"historical_profile": {
        "daily_avg_sales": 32000, "weekend_multiplier": "2.3x (Fri-Sun)", "past_edi_success_rate": 0.96,
        "supplier_payable_tomorrow": 4500, "active_lender": "Clix Capital",
        "daily_sales": [{"date": "2026-11-15", "gross": 18000, "note": "heavy rain"},
                        {"date": "2026-11-16", "gross": 20400, "note": "rain"}, {"date": "2026-11-17", "gross": 100000}],
        "connectors": [{"name": "Shiprocket Sync", "status": "active", "consent": "granted", "holds_pod_for": ["9981"]},
                       {"name": "VYAPAR_POS_SYNC", "status": "ACTIVE"}]}},
}

VARIANT_B = {  # different names, nesting and units
    "seed/merchant.json": {"merchant": {"merchant_id": "PAYTM_MERCH_8821", "business_name": "Sharma Electronics",
                                        "GSTIN": "07ABCDE1234F1Z5", "devices": [{"type": "SOUNDBOX", "serial": "SB-1"}]},
                           "historical_profile": {"avg_daily_sales": "₹32,000", "weekend_spike": 2.3,
                                                  "edi_success_pct": "96%", "tomorrow_stock_payable": "₹4,500",
                                                  "lender": "Clix Capital", "kfs_edi_holiday_eligible": "yes"}},
    "seed/settlement.json": {"settlements": [{"date": "2026-11-18", "gross": "₹1,00,000", "net_credit": 95840,
                                              "variance": 4160, "breakdown": {
                                                  "MDR Fee": 1450, "GST on MDR": 261,
                                                  "Customer Refund": {"amount": 1500, "order_id": "4412"},
                                                  "Soundbox Rental": 149,
                                                  "Chargeback Hold": {"amount": 800, "order_id": "9981", "status": "held"}}}]},
    "seed/transactions.json": [{"utr_number": "632184920111", "amount": "1,250", "app": "GPay", "state": "success"},
                               {"utr_number": "632184920999", "amount": 2400, "app": "PhonePe", "state": "pending"}],
    "seed/refunds_orders.json": {"orders": [{"order_id": "#4412", "type": "refund", "amount": 1500, "status": "PROCESSED"},
                                            {"order_id": "#9981", "type": "chargeback", "amount": 800, "status": "HELD"}],
                                 "refund_limit": 5000},
    "seed/loan.json": {"edi": "₹500", "balance": "₹42,000"},
    "seed/fee_rules.json": {"mdr": {"credit_card": "2%", "wallet_upi_above_2k": "1.1%", "bank_upi": "0%"},
                            "gst": {"rate_pct": 18}},
    "seed/initial_state.json": {"chargeback": {"order_id": "9981", "status": "HELD"}, "frauds_blocked_count": 0},
    "intents/utterances.json": [{"intent": "UTR_VERIFY", "utterances": ["ye payment asli hai kya"],
                                 "preset_chip": "Payment check karo"}],
    "golden/golden_paths.json": [{"step": 1, "trigger": "settlement kam kyun aaya", "expect": {"intent": "SETTLEMENT_RECONCILE"}}],
}


def write_dataset(root: Path, files: dict, test_files: bool = True) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
    if test_files:
        (root / "test_files").mkdir(exist_ok=True)
        for name in ("pod_9981.png", "fake_upi.png"):
            (root / "test_files" / name).write_bytes(PNG)
    return root


@pytest.fixture(scope="module")
def dir_a(tmp_path_factory):
    return write_dataset(tmp_path_factory.mktemp("dataset_a"), VARIANT_A)


@pytest.fixture(scope="module")
def dir_b(tmp_path_factory):
    return write_dataset(tmp_path_factory.mktemp("dataset_b"), VARIANT_B)


@pytest.fixture(autouse=True)
def _restore_builtin(client):
    yield
    use_dataset(NO_DATASET)
    client.post("/reset")


# ----------------------------------------------------------------------------- 1. loader


def test_missing_dataset_uses_builtin():
    d = use_dataset(NO_DATASET)
    assert set(d.sources.values()) == {"builtin (missing)"}
    assert d.settlement["variance"] == 4160 and d.refund_limit == 5000
    assert all(c["ok"] for c in d.checks())


def test_variant_a_normalises(dir_a):
    d = use_dataset(dir_a)
    assert set(d.sources.values()) == {"dataset"}, d.sources
    assert d.merchant["gstin"] == "07ABCDE1234F1Z5" and d.merchant["soundbox"]["device_id"] == "SBX-8821-01"
    s = d.settlement
    assert (s["gross"], s["net_bank_credit"], s["variance"]) == (100000, 95840, 4160)  # gross summed from the mix
    assert [x["head"] for x in s["deductions"]] == ["MDR_FEE", "GST_ON_MDR", "CUSTOMER_REFUND", "SOUNDBOX_RENTAL", "CHARGEBACK_HOLD"]
    assert d.deduction("CHARGEBACK")["order_id"] == "9981"
    assert all(c["ok"] for c in d.checks())
    assert set(d.utrs) == {"632184920111", "632184920999", "632184920222", "632184920333"}
    assert d.utrs["632184920333"]["status"] == "FAILED"
    assert d.refunds["4412"]["amount"] == 1500 and d.chargebacks["9981"]["pod_due_in_hours"] == 48
    assert d.refund_limit == 3000
    assert d.loan["balance"] == 42000 and d.loan["edi_per_day"] == 500
    assert d.fees["gst_rate_pct"] == 18
    assert d.fees["mdr_rates"] == {"credit_card": "2%", "wallet_on_upi_above_2000": "1.1%", "bank_upi": "0%"}
    assert d.initial_chargeback_status == {"9981": "HELD"}
    assert len(d.utterances) == 7 and len(d.presets()) == 3
    assert [s["name"] for s in d.golden_steps()] == ["settlement", "pod", "fake"]
    assert d.test_file("test_files/pod_9981.png") and d.test_file("fake_upi.png")
    h = d.history
    assert (h["daily_avg_sales"], h["weekend_multiplier"], h["past_edi_success_rate"]) == (32000, 2.3, 96)
    assert (h["supplier_payable_tomorrow"], h["active_lender"]) == (4500, "Clix Capital")
    assert [r["date"] for r in h["recent_daily_sales"] if r.get("dip")] == ["2026-11-15", "2026-11-16"]
    assert d.connector("SHIPROCKET_SYNC")["holds_pod_for"] == ["9981"] and d.connector("VYAPAR_POS_SYNC")


def test_variant_b_normalises_to_same_values(dir_b):
    d = use_dataset(dir_b)
    assert d.sources.pop("history") == "dataset (from merchant.json)"  # profile embedded in merchant.json
    assert set(d.sources.values()) == {"dataset"}, d.sources
    h = d.history
    assert (h["daily_avg_sales"], h["weekend_multiplier"], h["past_edi_success_rate"]) == (32000, 2.3, 96)
    assert (h["supplier_payable_tomorrow"], h["active_lender"], h["kfs"]["edi_holiday_eligible"]) == (4500, "Clix Capital", True)
    assert (d.merchant["mid"], d.merchant["name"], d.merchant["gstin"]) == ("PAYTM_MERCH_8821", "Sharma Electronics", "07ABCDE1234F1Z5")
    assert d.merchant["soundbox"]["serial"] == "SB-1"
    s = d.settlement
    assert (s["gross"], s["net_bank_credit"], s["variance"]) == (100000, 95840, 4160)
    assert {x["head"]: x["amount"] for x in s["deductions"]} == {
        "MDR_FEE": 1450, "GST_ON_MDR": 261, "CUSTOMER_REFUND": 1500, "SOUNDBOX_RENTAL": 149, "CHARGEBACK_HOLD": 800}
    assert d.deduction("CHARGEBACK")["status"] == "HELD"
    assert d.utrs["632184920111"]["amount"] == 1250 and d.utrs["632184920999"]["status"] == "PENDING"
    assert set(d.refunds) == {"4412"} and set(d.chargebacks) == {"9981"} and d.refund_limit == 5000
    assert (d.loan["edi_per_day"], d.loan["balance"]) == (500, 42000)
    assert d.fees["gst_rate_pct"] == 18 and d.fees["mdr_rates"]["wallet_upi_above_2k"] == "1.1%"
    assert {(u["text"], u["intent"], u["preset"]) for u in d.utterances} == {
        ("ye payment asli hai kya", "UTR_VERIFY", False), ("Payment check karo", "UTR_VERIFY", True)}
    assert d.golden_steps()[0]["text"] == "settlement kam kyun aaya"


def test_broken_file_falls_back_for_that_file_only(client, tmp_path):
    root = write_dataset(tmp_path, VARIANT_A)
    (root / "seed/settlement.json").write_text("{ oops", encoding="utf-8")
    (root / "seed/loan.json").write_text(json.dumps({"lender": "X"}), encoding="utf-8")
    d = use_dataset(root)
    assert d.sources["settlement"].startswith("builtin (unreadable")
    assert d.sources["loan"].startswith("builtin (unusable")
    assert d.sources["transactions"] == "dataset"
    assert d.settlement["variance"] == 4160  # built-in
    assert ask(client, "settlement kam kyun aaya").status_code == 200
    assert client.get("/health").json()["dataset"]["files"]["settlement"].startswith("builtin")


def test_partial_file_reports_fallback_fields(tmp_path):
    files = json.loads(json.dumps(VARIANT_A))
    del files["seed/settlement.json"]["deductions"]
    d = use_dataset(write_dataset(tmp_path, files))
    assert d.sources["settlement"] == "dataset (builtin for: deductions)"
    assert d.settlement["gross"] == 100000 and len(d.settlement["deductions"]) == 5


# ----------------------------------------------------------------------------- 2. wiring


def test_dataset_drives_mock_paytm_and_replies(client, dir_a):
    use_dataset(dir_a)
    client.post("/reset")
    extra = ask(client, "UTR 632184920222 ka payment aaya kya").json()
    assert extra["paytm_response"]["status"] == "SUCCESS" and extra["paytm_response"]["data"]["amount"] == 999
    failed = ask(client, "UTR 632184920333 check karo").json()
    assert failed["paytm_response"]["status"] == "FAILED" and "FAILED" in failed["reply_text"]
    assert ask(client, "order 5521 ka ₹4,000 refund kar do").json()["paytm_response"]["status"] == "ESCALATED"  # limit 3000
    assert ask(client, "order 5522 ka ₹2,000 refund kar do").json()["paytm_response"]["status"] == "INITIATED"
    settle = ask(client, "settlement kam kyun aaya").json()
    assert settle["gst_itc_logged"]["gstin"] == "07ABCDE1234F1Z5"
    assert settle["gst_itc_logged"]["basis"] == "18% GST on MDR ₹1,450 (ITC eligible)"
    assert client.get("/events").json()["merchant_order_sheet"]["gstin"] == "07ABCDE1234F1Z5"


def sent_to_paytm(body):
    """The A2A payload this request sent (a2a_events is the cumulative log, so match the request id)."""
    return next(e for e in body["a2a_events"]
                if e["type"] == "MERCHANT_TO_PAYTM" and e["request_id"] == body["request_id"])["payload"]["payload"]


def test_hardware_escalation_prefills_device(client, dir_a):
    use_dataset(dir_a)
    body = ask(client, "mera soundbox kharab ho gaya").json()
    sent = sent_to_paytm(body)
    assert sent["issue_type"] == "HARDWARE_SOUNDBOX" and sent["device"]["device_id"] == "SBX-8821-01"
    assert "Soundbox" in body["reply_text"]
    rental = ask(client, "soundbox ka rental kitna hai").json()  # not hardware: no device data shared
    assert rental["intent"] == "FEE_GST_LOAN"
    assert "device" not in sent_to_paytm(rental)


def test_utterance_bank_routes_what_keywords_miss(client, dir_a):
    use_dataset(dir_a)
    text = "Bhaiya mera paisa atka hua hai"
    assert router.keyword_intent(text) == "SETTLEMENT_RECONCILE"  # keywords alone get it wrong
    body = ask(client, text).json()
    assert (body["intent"], body["intent_source"]) == ("CHARGEBACK_RESOLVE", "utterance_bank")
    assert ask(client, "bhaiya mera paisa atka hua hai na").json()["intent"] == "CHARGEBACK_RESOLVE"  # near match


def test_presets_and_mock_transcript_follow_dataset(client, dir_a):
    use_dataset(dir_a)
    presets = client.get("/presets").json()
    assert presets["source"] == "dataset" and len(presets["presets"]) == 3
    r = client.post("/merchant/query-audio", files={"audio": ("q.webm", b"x", "audio/webm")},
                    data={"mid": "PAYTM_MERCH_8821", "consent_granted": "true"}).json()
    assert r["transcript"].startswith("Kal ₹1,00,000") and r["transcript_source"] == "mock"


def test_reset_reloads_dataset_from_disk(client, tmp_path):
    root = write_dataset(tmp_path, VARIANT_A)
    use_dataset(root)
    assert ask(client, "UTR 632184920444 check karo").json()["fraud_alert"] is not None
    tx = json.loads((root / "seed/transactions.json").read_text(encoding="utf-8"))
    tx["transactions"].append({"utr": "632184920444", "amount": 500, "payer_app": "GPay", "status": "SUCCESS"})
    (root / "seed/transactions.json").write_text(json.dumps(tx), encoding="utf-8")
    assert client.post("/reset").json()["dataset_files"]["transactions"] == "dataset"
    assert ask(client, "UTR 632184920444 check karo").json()["paytm_response"]["status"] == "SUCCESS"


def test_chargeback_state_persists_until_reset(client, dir_a):
    use_dataset(dir_a)
    client.post("/reset")
    assert upload(client, "pod_9981.png", PNG, "pod").json()["paytm_response"]["status"] == "RELEASED"
    after = ask(client, "settlement kam kyun aaya").json()
    hold = next(i for i in after["paytm_response"]["data"]["breakdown"] if i["head"] == "CHARGEBACK_HOLD")
    assert hold["status"] == "RELEASED" and "छुड़वा" not in after["reply_text"]  # no "send PoD" nudge any more
    client.post("/reset")
    assert ask(client, "chargeback 9981 ka kya hua").json()["paytm_response"]["status"] == "HELD"


# ----------------------------------------------------------------------------- 3. Person 1 (8001) compatibility


def _fake_8001(monkeypatch, *, llm_source="mock", llm_intent="REFUND_MANAGE", llm_reply="रिफंड हो गया है।"):
    """Stand in for services/sarvam_service with its real response shapes (schemas.py, mock.py)."""
    async def fake_post(base, path, **kwargs):
        req = httpx.Request("POST", f"{base}{path}")
        if path in ("/a2a/dispatch", "/ledger/reset"):  # 8002 stays down -> merchant-side mock Paytm
            raise httpx.ConnectError("8002 down", request=req)
        if path == "/doc-extract":
            fields = ({"order_id": "9981", "courier_name": "Delhivery", "amount": 800, "signature_present": True}
                      if kwargs["data"]["doc_type"] == "pod" else
                      {"utr": "632184920555", "amount": 1250, "payer_app": "GPay", "status": "SUCCESS"})
            return httpx.Response(200, request=req, json={"doc_type": kwargs["data"]["doc_type"], "extracted_fields": fields,
                                                          "confidence": 0.93, "warnings": [], "source": "mock"})
        if path == "/llm":
            if kwargs["json"]["response_format"] == "json":
                parsed = {"intent": llm_intent, "utr_number": None, "order_id": "4412", "amount": None,
                          "slots": {"utr_number": None, "order_id": "4412", "amount": None}}
                return httpx.Response(200, request=req, json={"reply": json.dumps(parsed), "parsed": parsed, "source": llm_source})
            return httpx.Response(200, request=req, json={"reply": llm_reply, "source": llm_source})
        if path == "/stt":
            return httpx.Response(200, request=req, json={"transcript": "मेरा कल का settlement ₹4,160 कम आया है, पैसा कहाँ कटा?",
                                                          "language_code": "hi-IN", "source": "mock"})
        if path == "/tts":
            return httpx.Response(200, request=req, json={"audio_base64": "UklGRiQAAABXQVZF", "mime_type": "audio/wav", "source": "mock"})
        raise AssertionError(path)

    monkeypatch.setattr(upstream, "_post", fake_post)


def test_person1_screenshot_utr_field_is_read(client, monkeypatch):
    _fake_8001(monkeypatch)
    body = upload(client, "fake_upi.png", PNG, "upi_screenshot").json()
    assert body["slots"]["utr_number"] == "632184920555"  # Person 1 calls it `utr`
    assert body["paytm_response"]["status"] == "NOT_FOUND_SUSPECTED_FAKE" and body["fraud_alert"]["priority"] == "HIGH"
    assert body["doc_extract"]["_source"] == "mock"


def test_person1_pod_releases_chargeback_with_correct_reply(client, monkeypatch):
    _fake_8001(monkeypatch)
    body = upload(client, "pod_9981.png", PNG, "pod").json()
    assert body["paytm_response"]["status"] == "RELEASED"
    assert body["reply_source"] == "template" and "RELEASED" in body["reply_text"]  # not Person 1's "upload your PoD" canned line


def test_person1_mock_llm_is_not_trusted(client, monkeypatch):
    _fake_8001(monkeypatch, llm_source="mock", llm_intent="REFUND_MANAGE")
    body = ask(client, "settlement kam kyun aaya").json()
    assert (body["intent"], body["intent_source"]) == ("SETTLEMENT_RECONCILE", "keyword_fallback")
    assert body["audio_source"] == "mock" and body["audio_base64"]


def test_person1_live_llm_is_used(client, monkeypatch):
    _fake_8001(monkeypatch, llm_source="sarvam", llm_intent="REFUND_MANAGE")
    body = ask(client, "us customer ka paisa lauta do").json()
    assert (body["intent"], body["intent_source"], body["slots"]["order_id"]) == ("REFUND_MANAGE", "llm", "4412")
    assert (body["reply_text"], body["reply_source"]) == ("रिफंड हो गया है।", "llm")


def test_person1_mock_stt_is_labelled(client, monkeypatch):
    _fake_8001(monkeypatch)
    body = client.post("/merchant/query-audio", files={"audio": ("q.webm", b"x", "audio/webm")},
                       data={"mid": "PAYTM_MERCH_8821", "consent_granted": "true"}).json()
    assert body["transcript_source"] == "mock" and body["intent"] == "SETTLEMENT_RECONCILE"


# ----------------------------------------------------------------------------- 4. the real team dataset

real = pytest.mark.skipif(not REAL_DATASET.is_dir(), reason=f"team dataset not found at {REAL_DATASET}")


@pytest.fixture
def real_dataset(client):
    d = use_dataset(REAL_DATASET)
    client.post("/reset")
    return d


@real
def test_real_dataset_every_file_parses(real_dataset):
    fallbacks = {k: v for k, v in real_dataset.sources.items() if not v.startswith("dataset") or "builtin for" in v}
    assert not fallbacks, f"dataset_loader didn't recognise these files' fields (extend its key lists): {fallbacks}"


@real
def test_real_dataset_settlement_adds_up(real_dataset):
    failed = [c for c in real_dataset.checks() if not c["ok"]]
    assert not failed, failed


@real
def test_real_utterances_route(real_dataset):
    wrong = [(u["text"], u["intent"], got.intent) for u in real_dataset.utterances
             if (got := asyncio.run(router.classify(u["text"]))).intent != u["intent"]]
    assert not wrong, wrong
    misses = [(u["text"], u["intent"], router.keyword_intent(u["text"])) for u in real_dataset.utterances
              if router.keyword_intent(u["text"]) != u["intent"]]
    if misses:  # informational: only matters for paraphrases when the LLM is down
        warnings.warn(f"keyword rules miss {len(misses)}/{len(real_dataset.utterances)} dataset utterances: {misses[:10]}")


@real
def test_real_golden_paths(client, real_dataset):
    steps = real_dataset.golden_steps()
    if not steps:
        pytest.skip("golden_paths.json has no steps this test can read")
    for step in steps:
        if step["text"]:
            body = ask(client, step["text"]).json()
        elif step["file"] and step["doc_type"]:
            path = real_dataset.test_file(step["file"])
            assert path, f"{step['name']}: test file {step['file']} not found"
            body = upload(client, path.name, path.read_bytes(), step["doc_type"]).json()
        else:
            continue
        if step["intent"]:
            assert body["intent"] == step["intent"], step
        if isinstance(step["status"], str):
            want, got = step["status"].upper(), str(body["paytm_response"]["status"]).upper()
            assert want in got or got in want, (step, got)
        if step["gst_itc"]:
            assert any(e["amount"] == step["gst_itc"] for e in body["local_gst_itc_log"]), step
        if step["fraud_alert"] is True:
            assert body["fraud_alert"], step


@real
def test_real_test_files(client, real_dataset):
    pod, fake = real_dataset.test_file("pod_9981.png"), real_dataset.test_file("fake_upi.png")
    assert pod, "pod_9981.png expected (dataset test_files/ or Person 1's samples/)"
    assert upload(client, pod.name, pod.read_bytes(), "pod").json()["paytm_response"]["status"] == "RELEASED"
    if fake:  # the data/seed layout ships no fake screenshot; the fraud path is covered by fake_upi.png elsewhere
        assert upload(client, fake.name, fake.read_bytes(), "upi_screenshot").json()["fraud_alert"] is not None
