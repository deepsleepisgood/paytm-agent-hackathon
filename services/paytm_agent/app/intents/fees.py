"""FEE_GST_LOAN — "what was this charge?", for fees, the GST on them, or the loan.

Three topics behind one intent, because that is how the contract has it and how a
merchant thinks about it: all three are money that left without them doing anything.

Nothing here decides anything; it reads and explains. The only judgement is the one
RiskPolicyAgent makes about whether the GST claim is safe to state, which depends on
the merchant actually being registered.
"""
from __future__ import annotations

from .. import templates
from ..errors import PayloadError
from ..mesh import Case
from ..seed import GST_RATE_PERCENT

TOPICS = ("FEE", "GST", "LOAN")

# Used when the caller sends no topic, which the merchant agent often will: the
# contract makes it optional, and refusing over a missing hint would be perverse when
# the merchant's own words say which one they mean.
_HINTS = (
    ("LOAN", ("loan", "edi", "emi", "kisht", "instalment", "installment", "किस्त", "लोन")),
    ("GST", ("gst", "itc", "input tax", "tax")),
    ("FEE", ("fee", "mdr", "charge", "commission", "कटा", "कमीशन")),
)


def _topic(req) -> str:
    asked = (req.payload or {}).get("topic")
    if asked:
        asked = str(asked).upper()
        if asked not in TOPICS:
            raise PayloadError(f"topic must be one of {list(TOPICS)}")
        return asked

    said = (req.merchant_said or "").lower()
    for topic, words in _HINTS:
        if any(w in said for w in words):
            return topic
    return "FEE"


def gather(case: Case) -> str:
    """IntelligenceAgent: pull the figures behind whichever charge is being asked about."""
    led = case.ledger
    topic = _topic(case.req)
    case.data = {"topic": topic}

    if topic == "FEE":
        case.data |= {
            "mdr_total_inr": led.mdr_total_inr,
            "breakdown": [b.as_dict() for b in led.mdr_bands],
        }
        return (
            f"Read the fee breakdown: {led.mdr_total_inr} across "
            f"{len(led.mdr_bands)} payment types"
        )

    if topic == "GST":
        case.data |= {
            "gst_inr": led.gst_on_mdr_inr,
            "rate_percent": GST_RATE_PERCENT,
            "base": "MDR_FEE",
            "base_inr": led.mdr_total_inr,
            "itc_eligible": led.gst_registered,
            "assumes_gst_registered": led.gst_registered,
        }
        return (
            f"Read GST of {led.gst_on_mdr_inr} at {GST_RATE_PERCENT:g}% on fees of "
            f"{led.mdr_total_inr}"
        )

    loan = led.loan
    case.data |= {
        "edi_per_day_inr": loan.edi_per_day_inr,
        "balance_inr": loan.balance_inr,
        "next_deduction_date": loan.next_deduction_date,
        "edi_tomorrow_inr": loan.edi_due_tomorrow_inr,
        "loan_edi_status": loan.status,
        "nbfc": loan.nbfc,
        "collection_method": loan.collection_method,
        "effect": (
            f"Tomorrow's instalment is {loan.edi_due_tomorrow_inr}."
            if loan.status == "ACTIVE"
            else f"The instalment is {loan.status}, so nothing is due tomorrow."
        ),
    }
    return (
        f"Read the loan: {loan.edi_per_day_inr} a day, {loan.balance_inr} outstanding, "
        f"status {loan.status}"
    )


def assess(case: Case) -> str:
    """RiskPolicyAgent: all three are explanations of the merchant's own charges."""
    data = case.data

    if data["topic"] == "GST" and not data["itc_eligible"]:
        # Telling an unregistered merchant they can reclaim GST would have them file a
        # credit they are not entitled to.
        case.escalate(
            "OUT_OF_SCOPE",
            "GST input credit depends on the merchant's registration, which is not "
            "confirmed on this account",
        )
        return "Cannot confirm GST registration, so the input credit claim needs a person"

    return f"A {data['topic'].lower()} charge on the merchant's own account: safe to explain"


def resolve(case: Case) -> str:
    """ResolutionAgent: say what the charge was and what it means."""
    data = case.data
    topic = data["topic"]

    if case.escalated:
        case.found = case.reason_text
        case.action_taken = "Explained the amount; the tax position needs a person"
        case.tried = ["Pulled the GST charged on this settlement"]
        case.template_text = templates.render("FEE_GST_LOAN", data, "ESCALATED")
        return "Gave the amount and handed the tax question over"

    if topic == "FEE":
        case.found = (
            f"Fees {data['mdr_total_inr']} = "
            + " + ".join(f"{b['type']} {b['fee_inr']}" for b in data["breakdown"])
        )
    elif topic == "GST":
        case.found = (
            f"GST {data['gst_inr']} at {data['rate_percent']:g}% on fees of {data['base_inr']}"
        )
    else:
        case.found = (
            f"Loan {data['edi_per_day_inr']}/day, {data['balance_inr']} outstanding, "
            f"next on {data['next_deduction_date']}"
        )

    case.action_taken = "None, explained only"
    case.template_text = templates.render("FEE_GST_LOAN", data, "RESOLVED")
    return f"Explained the {topic.lower()} charge from the ledger"
