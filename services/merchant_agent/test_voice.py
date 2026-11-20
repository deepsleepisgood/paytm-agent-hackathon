"""voice.py: the voice says the answer, any question / warning / action and one severity line; the screen keeps the rest."""
from __future__ import annotations

import pytest

import voice
from conftest import ask

TIP = "PoD ke saath pichhle 4 mein se 4 disputes aap jeete hain."
SETTLE = ("₹4,160 mein MDR ₹1,450, GST ₹261, refund ₹1,500, soundbox ₹149 aur #9981 ka ₹800 chargeback hold hai — ₹261 "
          "ITC maine log kar diya. Delivery proof bhejiye, hold hat jayega. " + TIP)


def test_a_list_of_amounts_becomes_the_total_and_the_two_biggest():
    said = voice.spoken(SETTLE, tip=TIP)
    assert said.startswith("₹4,160 mein MDR ₹1,450, refund ₹1,500.")
    assert "GST ₹261" not in said and "ITC" not in said and TIP not in said
    assert "Delivery proof bhejiye" in said and "screen par" in said
    assert len(said.split()) <= voice.MAX_WORDS < len(SETTLE.split())


def test_indian_number_commas_are_not_list_separators():
    assert voice._AMOUNT.findall("MDR ₹1,450, GST ₹261, ₹1,50,000") == ["₹1,450", "₹261", "₹1,50,000"]


def test_a_consent_question_is_never_dropped():
    txt = ("Kal ₹6,500 ka refund jayega toh payout sirf ₹3,200 bachega, jabki ₹18,000 ka stock dena hai. Loan EDI 2 din "
           "ke liye rok doon? ₹1,000 bachenge.")
    assert "rok doon?" in voice.spoken(txt)


def test_a_safety_warning_is_kept_and_long_references_are_shortened():
    txt = ("Dhyan dijiye: UTR 632184920555 aapke Paytm account mein nahi mila. Jab tak paisa account mein na dikhe, saman "
           "mat dijiye. Maine ise risk alert ke roop mein note kar liya hai.")
    said = voice.spoken(txt, voice_line="Paytm specialist 30 minute mein call karenge.")
    assert "saman mat dijiye" in said and said.endswith("30 minute mein call karenge.")
    assert "632184920555" not in said and "UTR 0555" in said
    assert "risk alert" not in said


def test_what_was_done_is_said_and_the_tip_is_not():
    tip = "Sunita Yadav aapke repeat customer hain, turant refund se bharosa badhega."
    txt = f"Customer ne order #4489 ke ₹1,180 do baar diye the. Duplicate ₹1,180 ka refund shuru kar diya, T+1 mein pahunchega. {tip}"
    said = voice.spoken(txt, tip=tip)
    assert "refund shuru kar diya" in said and "Sunita" not in said


def test_english_stays_english():
    txt = ("₹4,160 was deducted: MDR ₹1,450, GST ₹261, refund ₹1,500, Soundbox ₹149, and a ₹800 chargeback hold (9981). "
           "Send the delivery proof and the hold will be released.")
    said = voice.spoken(txt, lang="en")
    assert said.endswith("The details are on your screen.") and "Send the delivery proof" in said


# ----------------------------------------------------------------------------- through the API
@pytest.fixture(autouse=True)
def clean(client):
    client.post("/reset")
    yield
    client.post("/reset")


def test_every_answer_carries_a_short_spoken_form(client):
    for text in ("Kal settlement kam kyun aaya?", "Customer ne order 4489 ke liye do baar payment kar diya",
                 "Mujhe ek pizza order karna hai"):
        r = ask(client, text).json()
        assert r["spoken_text"] and len(r["spoken_text"].split()) <= voice.MAX_WORDS
        assert len(r["spoken_text"].split()) <= len(r["reply_text"].split())


def test_a_clarifying_question_is_spoken_short_and_still_asks(client):
    r = ask(client, "Mujhe ek pizza order karna hai").json()
    assert r["intent"] == "UNCLEAR" and r["spoken_text"].endswith("?")
    assert len(r["spoken_text"].split()) < len(r["reply_text"].split())


def test_fallback_speaks_a_short_line_not_the_case_paragraph(client, monkeypatch):
    monkeypatch.setenv("TRIAGE_FALLBACK", "1")
    r = ask(client, "Customer ne order 4489 ke liye do baar payment kar diya").json()   # Paytm offline: MEDIUM retry
    assert r["triage"]["fallback"] == "AUTO_RETRY"
    assert "RTY-" in r["reply_text"] and "RTY-" not in r["spoken_text"]
    assert "kuch change nahi kiya" in r["spoken_text"]


def test_what_the_merchant_must_do_survives_the_cap():
    txt = ("Market band se sale 37% giri, isliye ₹500 EDI fail hui, default nahi. 1-tap UPI link se aaj bhariye, penalty "
           "nahi; chahein toh 2 din ka KFS pause bhi hai.")
    assert "UPI link se aaj bhariye" in voice.spoken(txt)


def test_ticket_and_case_ids_are_not_read_out():
    said = voice.spoken("Maine Soundbox ki kharabi ka maamla Paytm ki L2 team ko bhej diya hai, ticket tkt_002. 2 ghante "
                        "mein aapko callback aayega.", voice_line="Paytm specialist (case HND-0001) 2 ghante mein call karenge.")
    assert "tkt_002" not in said and "HND-0001" not in said and "bhej diya hai." in said
