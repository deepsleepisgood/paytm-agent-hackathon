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
        # Says the instalment is due, not that the payout is reduced by it. The
        # canonical loan data is explicit that the EDI is collected by eNACH from the
        # bank account rather than netted from a settlement, so the narrower claim is
        # the one that is true either way.
        text += (
            f" Your {rupees(up['amount_inr'])} {up['label'].lower()} is also due on "
            f"{pretty_date(up['date'])}."
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

    if lookup == "REVERSED":
        return (
            f"Reference {utr} for {rupees(data['amount_inr'])} did arrive, but it has "
            "since been reversed and the money has gone back to your customer, so it is "
            "not in your account now. Please do not treat this one as paid."
        )

    if lookup == "FAILED":
        # Names the cause without blaming the customer: an MPIN slip or a declined
        # confirmation is nobody's bad faith, and the merchant has to serve this person.
        why = data.get("failure_reason")
        return (
            f"That payment did not go through. Reference {utr} for "
            f"{rupees(data['amount_inr'])} was declined"
            + (f" — {why.lower()} — " if why else " ")
            + "so nothing was taken from your customer's account. Please ask them to "
            "try again, and hold the goods until it shows as received."
        )

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


def _mandate_troubleshoot(data: dict[str, Any], status: str) -> str:
    """Opens by saying what it is not.

    A bounce notice reads like default, and that fear is the actual problem to solve
    before any remedy is useful.
    """
    if not data.get("overdue_amount_inr"):
        return (
            f"Your instalment mandate {data['mandate_id']} is active and there is "
            "nothing outstanding on it."
        )

    amount = rupees(data["amount_inr"])
    history = data["repayment_history"]
    opener = (
        f"Your {amount} instalment could not be collected from your bank on "
        f"{pretty_date(data['last_return_date'])}, because the balance was short. "
        "This is not a default, and it is not a mark against you: you have paid "
        f"{history['on_time_rate_percent']}% of your instalments on time over the last "
        f"{history['months']} months, and your mandate is still active."
    )

    if status == "ESCALATED":
        return (
            opener + f" You can clear it now with a UPI link for {amount}. I have also "
            "asked a Paytm colleague to look at your account, because a payment holiday "
            "is not available to you at the moment."
        )

    pause = next((r for r in data["remedies"] if r["type"] == "KFS_HARDSHIP_PAUSE"), None)
    text = opener + f" You have two choices. I can send you a UPI link to pay the {amount} now."
    if pause:
        text += (
            f" Or, if money is tight this week, {pause['nbfc']} can pause your daily "
            f"instalment for {pause['pause_days']} days, which keeps "
            f"{rupees(pause['edi_saved_inr'])} with you. Just tell me which you prefer."
        )
    return text


def _duplicate_payment_reconcile(data: dict[str, Any], status: str) -> str:
    if data["duplicates_found"] == 0:
        return (
            "I have checked your payments and no order has been paid for twice, so "
            "there is nothing to put right."
        )

    order = data["order_id"]
    amount = rupees(data["refund"]["amount_inr"])

    if data.get("already_refunded"):
        return (
            f"Your customer did pay twice for order {order}, but the extra {amount} has "
            "already gone back to them. Your account is square."
        )

    if status == "ESCALATED":
        return (
            f"Your customer paid twice for order {order}. The extra {amount} is larger "
            "than I am allowed to return on my own, so a Paytm colleague will release it. "
            "You have not lost anything: the second payment was never really yours."
        )

    return (
        f"Your customer paid twice for order {order}, {amount} each time, under a minute "
        f"apart. I have sent the second {amount} back to them. Nothing changes for you: "
        "you were credited twice, so your account is square either way."
    )


def _working_capital_advisory(data: dict[str, Any], status: str) -> str:
    sales = data["sales"]
    daily = rupees(sales["avg_daily_sales_inr"])
    weekend = rupees(data["weekend_daily_sales_inr"])
    loan = data["existing_loan"]

    pattern = (
        f"Over the last {sales['months']} months you have taken about {daily} a day, and "
        f"{sales['busiest_days'][0]} to {sales['busiest_days'][-1]} runs about "
        f"{sales['weekend_multiplier']} times that, around {weekend} a day. So it is "
        f"worth having your stock in by {sales['restock_by']}."
    )

    if status == "ESCALATED":
        # The refusal. Said plainly, and without leaving the merchant empty-handed.
        # Phrased to avoid containing the recommendation it is declining to make, even
        # as a quotation of the question. A test forbids those phrases outright, and a
        # strict check is worth more than a reworded exception to it.
        return (
            pattern + " On whether to take the working capital, I am not the right one "
            "to answer that: it depends on things I cannot see, and it is your business "
            "at stake. I have asked a Paytm colleague to go through it with you properly."
        )

    repay = data["share_of_daily_takings_repaid_percent"]
    return (
        pattern + f" On the loan you already have with {loan['nbfc']}, "
        f"{rupees(loan['balance_inr'])} is left at {loan['apr_percent']}% a year, and "
        f"the {rupees(loan['edi_per_day_inr'])} daily instalment is about {repay}% of an "
        "average day's takings. If you ever want more working capital, you would get a "
        "Key Fact Statement with the full rate and term before taking any of it."
    )


def _cashflow_edi_switch(data: dict[str, Any], status: str) -> str:
    payout = rupees(data["projected_net_payout"])
    b = data["breakdown"]
    offer = data.get("edi_pause_offer") or {}

    why = (
        f"Tomorrow's payout is looking like {payout}: about "
        f"{rupees(b['expected_gross_inr'])} in sales, less "
        f"{rupees(b['pending_refunds_inr'])} going back to a customer"
        + (f" and {rupees(b['edi_due_inr'])} for your loan instalment."
           if b["edi_due_inr"] else ".")
    )

    if status == "ESCALATED":
        return (
            why + " Your loan is not eligible for a payment holiday, so I have asked a "
            "Paytm colleague to take it up with the lender for you."
        )

    if not offer.get("eligible"):
        return why + f" Your instalment is already paused, so nothing more comes out tomorrow."

    return (
        why + f" If that leaves you short, {offer['nbfc']} can pause your "
        f"{rupees(b['edi_due_inr'] or 500)} daily instalment for {offer['pause_days']} "
        f"days, keeping {rupees(offer['edi_saved_inr'])} with you. Say the word and I "
        "will set it up."
    )


RENDERERS = {
    "ESCALATE_HUMAN": _escalate_human,
    "SETTLEMENT_RECONCILE": _settlement_reconcile,
    "UTR_VERIFY": _utr_verify,
    "CHARGEBACK_RESOLVE": _chargeback_resolve,
    "MANDATE_TROUBLESHOOT": _mandate_troubleshoot,
    "DUPLICATE_PAYMENT_RECONCILE": _duplicate_payment_reconcile,
    "WORKING_CAPITAL_ADVISORY": _working_capital_advisory,
    "CASHFLOW_EDI_SWITCH": _cashflow_edi_switch,
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
