"""The plain-English sentence that goes back with every answer.

`template_text` is the contract's fallback: if Person 3's language model is slow or
fails, this is what the merchant hears. It is built by string formatting over `data`
and nothing else.

Keeping it in one small file is what makes two rules auditable at a glance:
  - no arithmetic happens here, only formatting of numbers already computed;
  - nothing accusatory is ever said about a payment (see BANNED_WORDS).
"""
from __future__ import annotations

from typing import Any

# Never say these to a merchant about a payment. An unknown UTR means "not in your
# account", which is what we can actually prove. Calling it fake accuses the merchant's
# customer on the strength of a database miss.
BANNED_WORDS = ("fake", "fraud", "scam", "suspicious")


def rupees(amount: int | float) -> str:
    """Indian digit grouping with the symbol, e.g. 95840 -> '₹95,840'.

    Grouped on purpose: Person 1's text-to-speech reads "₹95,840" as an amount and a
    bare "95840" as a string of digits, so the grouping is what makes it sound right.
    Their README asks for exactly this form.
    """
    return f"₹{_grouped(int(round(amount)))}"


def _grouped(n: int) -> str:
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) <= 3:
        return f"{sign}{s}"
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return f"{sign}{','.join(parts)},{tail}"


MONTHS = ("January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December")


def pretty_date(iso_date: str) -> str:
    """'2026-11-18' -> '18 November'. Falls back to the raw string if it is not a date."""
    try:
        y, m, d = (int(p) for p in iso_date.split("-")[:3])
        return f"{d} {MONTHS[m - 1]}"
    except (ValueError, IndexError):
        return iso_date


def _escalate_human(data: dict[str, Any], status: str) -> str:
    return (
        "I have passed this to a Paytm support colleague with everything we discussed, "
        "so you will not have to explain it again. They will come back to you."
    )


def _settlement_reconcile(data: dict[str, Any], status: str) -> str:
    gross = rupees(data["gross_inr"])
    net = rupees(data["net_credit_inr"])
    gap = rupees(data["variance_inr"])
    when = pretty_date(data["settlement_date"])

    if status == "ESCALATED":
        # We can see the gap but cannot fully explain it. Say exactly that: reciting a
        # partial list as if it were the whole answer is how a merchant loses trust.
        return (
            f"Your sales on {when} were {gross} and {net} reached your bank, "
            f"a difference of {gap}. I can account for part of that but not all of it, "
            "so I have asked a Paytm colleague to pull your full settlement report and "
            "come back to you."
        )

    # Labels are kept exactly as the ledger writes them. Lower-casing them turned
    # "GST on fees" into "gst on fees", and the labels already read as English.
    # Semicolons, not commas: several labels contain their own numbers
    # ("Refund for order 4412"), and commas run them together when spoken.
    items = "; ".join(
        f"{line['label']} {rupees(line['amount_inr'])}" for line in data["lines"]
    )
    text = (
        f"Your sales on {when} were {gross} and {net} reached your bank. "
        f"The difference of {gap} is: {items}."
    )
    for up in data.get("upcoming", []):
        text += (
            f" Your next payout on {pretty_date(up['date'])} will also be "
            f"{rupees(up['amount_inr'])} lower for your {up['label'].lower()}."
        )
    return text


RENDERERS = {
    "ESCALATE_HUMAN": _escalate_human,
    "SETTLEMENT_RECONCILE": _settlement_reconcile,
}


def render(intent: str, data: dict[str, Any], status: str = "RESOLVED") -> str:
    renderer = RENDERERS.get(intent)
    if renderer is None:
        # A handler exists but its sentence has not been written yet. Say something
        # true and neutral rather than leaking a dict to the merchant.
        return "I have checked your account and recorded the details of this request."
    text = renderer(data, status)
    assert not any(w in text.lower() for w in BANNED_WORDS), (
        f"{intent} template contains a banned word: {text!r}"
    )
    return text
