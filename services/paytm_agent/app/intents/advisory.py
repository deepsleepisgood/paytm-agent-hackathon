"""WORKING_CAPITAL_ADVISORY — "how do I grow?", and sometimes "should I take the loan?"

This is the one intent where the right answer is partly a refusal, and it is worth being
explicit about why.

Reading a merchant's own sales back to them is useful and safe: their takings average
₹32,000 a day, weekends run 2.3 times weekday trade, so stock up by Thursday. That is
their own data, and the agent is only arithmetic and a calendar.

Telling a shopkeeper to borrow is something else. It is a recommendation about taking on
debt, made by software, to someone whose livelihood depends on it, with no view of their
other obligations. So:

  the agent will state the facts   what is pre-approved, and what the daily repayment
                                   would do to their payout
  the agent will not advise        any request for a recommendation goes to a human

No interest rate or tenure is quoted either. Those belong in the NBFC's Key Fact
Statement, which the merchant must see before accepting anything — inventing them for a
smoother demo would be putting made-up credit pricing in front of a merchant.

sarvam_service's Hindi reply takes the same line: it gives the sales pattern, says stock
up by Thursday, and mentions working capital with a clear KFS is available "if needed".
"""
from __future__ import annotations

from .. import templates
from ..mesh import Case

# Words that turn a question about facts into a request for a recommendation.
_ADVICE_WORDED = (
    "should i", "should we", "shall i", "recommend", "advise me", "is it worth",
    "worth taking", "good idea", "better to", "loan lena", "lena chahiye",
    "theek rahega", "faida",
)


def _asks_for_a_recommendation(req) -> bool:
    text = f"{req.merchant_said or ''} {(req.payload or {}).get('question', '')}".lower()
    if (req.payload or {}).get("wants_recommendation"):
        return True
    return any(phrase in text for phrase in _ADVICE_WORDED)


def gather(case: Case) -> str:
    """IntelligenceAgent: the merchant's own trading pattern and what is pre-approved."""
    led = case.ledger
    sales = led.sales
    loan = led.loan

    weekend_daily = int(round(sales.avg_daily_sales_inr * sales.weekend_multiplier))
    daily_repayment = loan.edi_per_day_inr

    case.data = {
        "sales": sales.as_dict(),
        "weekend_daily_sales_inr": weekend_daily,
        # The loan they already have, on its real terms. There is no pre-approved new
        # facility in the dataset, so none is offered or implied.
        "existing_loan": {
            "loan_id": loan.loan_id,
            "nbfc": loan.nbfc,
            "sanctioned_inr": loan.sanctioned_inr,
            "balance_inr": loan.balance_inr,
            "apr_percent": loan.apr_percent,
            "edi_per_day_inr": daily_repayment,
        },
        # The number that actually matters to a shopkeeper, and the one a glossy offer
        # usually leaves out.
        "share_of_daily_takings_repaid_percent": round(
            daily_repayment / sales.avg_daily_sales_inr * 100, 2
        ),
        "new_facility_offered": False,
        "is_recommendation": False,
    }
    return (
        f"Read {sales.months} months of trading: {sales.avg_daily_sales_inr} a day on "
        f"average, {sales.weekend_multiplier}x at weekends, against a "
        f"{loan.balance_inr} balance at {loan.apr_percent}% APR"
    )


def assess(case: Case) -> str:
    """RiskPolicyAgent: facts yes, recommendation no."""
    if _asks_for_a_recommendation(case.req):
        case.escalate(
            "OUT_OF_SCOPE",
            "The merchant asked whether they should borrow. That is a recommendation "
            "about taking on debt, which this agent does not make.",
        )
        return (
            "This is a request for a recommendation about borrowing, not for facts: "
            "a person should answer it"
        )

    return (
        "A question about the merchant's own sales and an existing pre-approved limit: "
        "safe to state the facts, with no recommendation attached"
    )


def resolve(case: Case) -> str:
    """ResolutionAgent: the pattern, the cost, and no nudge."""
    data = case.data
    sales = data["sales"]

    if case.escalated:
        case.found = "Merchant asked whether to take working capital"
        case.action_taken = "Gave no recommendation; handed to a person"
        case.tried = [
            "Shared the sales pattern and the pre-approved limit",
            "Did not advise for or against borrowing",
        ]
        case.template_text = templates.render("WORKING_CAPITAL_ADVISORY", data, "ESCALATED")
        return "Gave the numbers, declined to recommend, and handed it to a person"

    case.found = (
        f"{sales['avg_daily_sales_inr']} average daily takings over {sales['months']} "
        f"months, {sales['weekend_multiplier']}x at weekends; restock by "
        f"{sales['restock_by']}; existing balance "
        f"{data['existing_loan']['balance_inr']} at {data['existing_loan']['apr_percent']}% APR"
    )
    case.action_taken = "None, explained only"
    case.template_text = templates.render("WORKING_CAPITAL_ADVISORY", data, "RESOLVED")
    return (
        f"Explained the weekend pattern and to restock by {sales['restock_by']}, and "
        "stated the existing loan's real cost without recommending anything further"
    )
