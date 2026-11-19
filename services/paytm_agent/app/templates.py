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


def _utr_verify(data: dict[str, Any], status: str) -> str:
    """What the shopkeeper hears while the customer is still standing there.

    Every branch avoids the word the merchant must not repeat to their customer. The
    strongest thing said about a missing payment is that it is not in the account.
    """
    utr = data["utr"]
    lookup = data["lookup_status"]

    if status == "ESCALATED":
        return (
            "Several of the payment references you have given me are not in your "
            "account. Please do not hand over any goods for them. I am asking a Paytm "
            "colleague to call you about this straight away."
        )

    if lookup == "SUCCESS_SETTLED":
        text = (
            f"Yes, {rupees(data['amount_inr'])} came in from {data['payer_app']} "
            f"on reference {utr} and it has been settled to you. You can hand over the goods."
        )
        if data.get("amount_matches_claim") is False:
            text += (
                f" One thing to check: the amount that arrived is "
                f"{rupees(data['amount_inr'])}, which is not what you were told."
            )
        return text

    if lookup == "PENDING":
        return (
            f"Reference {utr} for {rupees(data['amount_inr'])} from {data['payer_app']} "
            "is still being processed. It is not in your account yet. If it does not go "
            "through, it reverses to the customer by the next working day on its own, so "
            "please wait before handing over the goods."
        )

    # NOT_FOUND. The one sentence this whole module exists to get right.
    return (
        f"I cannot find reference {utr} in your account, so please do not hand over the "
        "goods yet. It may have been typed differently, or paid into another account. "
        "I can open a ticket so someone checks it properly for you."
    )


def _chargeback_resolve(data: dict[str, Any], status: str) -> str:
    held = rupees(data["amount_held_inr"])
    order = data["order_id"]
    hours = data.get("hours_left")

    if status == "ACTION_REQUIRED":
        return (
            f"A customer has disputed the payment on order {order}, so {held} of your "
            f"settlement is being held while it is looked into. If you send me the "
            f"delivery proof for that order in the next {int(hours)} hours, I will "
            "submit it for you and the money should come back."
        )

    if status == "ESCALATED":
        # Says what is wrong and what happens next, without blaming the merchant for a
        # blurry photo or a passed deadline.
        return (
            f"I have your document, but I am not able to submit it myself for order "
            f"{order}. I have passed it to a Paytm colleague with everything you sent, "
            f"and they will take it forward before the deadline. The {held} stays held "
            "until the dispute is decided."
        )

    return (
        f"Your delivery proof for order {order} has been submitted as evidence, and the "
        f"{held} that was being held has been released back to you. It will come through "
        "in your next settlement. The bank still makes the final decision on the dispute, "
        "so I will let you know if anything changes."
    )


RENDERERS = {
    "ESCALATE_HUMAN": _escalate_human,
    "SETTLEMENT_RECONCILE": _settlement_reconcile,
    "UTR_VERIFY": _utr_verify,
    "CHARGEBACK_RESOLVE": _chargeback_resolve,
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
