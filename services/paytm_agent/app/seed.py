"""The merchant's ledger: the single source of every rupee figure in this service.

Two design rules, both there to stop the demo contradicting itself:

1. **Derive, never repeat.** The MDR fee is the sum of the per-instrument bands, and the
   GST line is a percentage of that fee. They are computed, not typed twice. The contract
   quotes the same 1,450 in two places (the settlement breakdown and the FEE topic); if
   both were literals, editing one would silently desync the demo.

2. **Facts and explanations are separate.** `gross_inr` and `net_credit_inr` are facts the
   bank reports. The deduction lines are this service's *explanation* of the difference.
   They can fail to add up — that is exactly the SETTLEMENT_UNRECONCILED case — so
   `reconciles` is computed by comparing the two, never assumed.

Figures marked (assumption) are not verified Paytm policy. They are labelled here and in
the demo, and are open questions for the Paytm mentor.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import clock

# --- Fixed facts about the demo merchant ----------------------------------------------
MID = "PAYTM_MERCH_8821"
MERCHANT_NAME = "Sharma Electronics"
GST_REGISTERED = True  # (assumption) ITC on MDR only applies if the merchant is registered

SETTLEMENT_DATE = "2026-11-18"
GROSS_SALES_INR = 100_000
NET_BANK_CREDIT_INR = 95_840  # what the bank actually credited: a fact, not a calculation

GST_RATE_PERCENT = 18.0
SOUNDBOX_RENTAL_INR = 149  # (assumption) that soundbox rental is netted off the settlement

CHARGEBACK_DEFAULT_HOURS = 48

# --- V2 delta: the loan behind the EDI, and the consented connectors -------------------
NBFC_NAME = "Clix Capital"
KFS_CLAUSE = "4.2"
KFS_MAX_PAUSE_DAYS = 2  # KFS clause 4.2 caps a hardship pause at two days

# Tomorrow's expected gross, before the refund and the EDI come out of it. Seeded so the
# projected payout is a calculation rather than the literal 1,200 the contract quotes:
#   5,200 gross - 3,500 refund - 500 EDI = 1,200
PROJECTED_GROSS_TOMORROW_INR = 5_200


@dataclass(frozen=True)
class MdrBand:
    """One payment instrument's share of the MDR fee."""

    type: str
    volume_inr: int
    rate_percent: float
    note: str = ""

    @property
    def fee_inr(self) -> int:
        return int(round(self.volume_inr * self.rate_percent / 100))

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "volume_inr": self.volume_inr,
            "rate_percent": self.rate_percent,
            "fee_inr": self.fee_inr,
        }


# Volumes and rates from the team's canonical dataset
# (data/seed/settlement_breakdown_2026-11-18.json), not chosen by us. They add to the
# 1,450 the contract quotes. Earlier these were a plausible split of our own invention,
# which would have had this service quoting a different fee breakdown from the dataset
# for the same question.
MDR_BANDS: tuple[MdrBand, ...] = (
    MdrBand("Credit card and postpaid", 62_600, 2.0),
    MdrBand("Wallet-on-UPI above 2000", 18_000, 1.1),
    MdrBand("UPI person-to-merchant", 19_400, 0.0, note="zero MDR on bank-to-bank UPI"),
)


@dataclass
class Order:
    order_id: str
    amount_inr: int
    settled: bool
    refund_status: str  # NONE | PENDING | PROCESSED
    refund_amount_inr: int | None = None
    # Whether this refund was one of the deductions in the settlement that has already
    # run. A refund issued today is real, but it is not part of yesterday's arithmetic,
    # and counting it there would make a closed settlement stop reconciling.
    in_settlement: bool = False

    def as_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "amount_inr": self.amount_inr,
            "settled": self.settled,
            "refund_status": self.refund_status,
            "refund_amount_inr": self.refund_amount_inr,
            "in_settlement": self.in_settlement,
        }


@dataclass
class UpiTxn:
    utr: str
    amount_inr: int
    payer_app: str
    lookup_status: str  # SUCCESS_SETTLED | PENDING
    order_id: str | None = None
    received_at: str | None = None
    refunded: bool = False

    def as_dict(self) -> dict:
        return {
            "utr": self.utr,
            "amount_inr": self.amount_inr,
            "payer_app": self.payer_app,
            "lookup_status": self.lookup_status,
            "order_id": self.order_id,
            "received_at": self.received_at,
            "refunded": self.refunded,
        }


@dataclass
class Mandate:
    """The eNACH auto-debit the daily loan instalment is collected on.

    Figures marked (assumption) are not published Paytm or NBFC policy.
    """

    mandate_id: str = "UMRN-DEMO-0000008821"
    amount_inr: int = 500
    status: str = "BOUNCED"  # ACTIVE | BOUNCED
    bounce_date: str = "2026-11-17"
    bounce_reason: str = "INSUFFICIENT_FUNDS"
    # Nil, not a penalty. KFS clause 4.1 lets a bounced EDI be paid the same day by UPI
    # link without charge, and the dataset records bounce charges as waived for
    # first-attempt friction. A fee we invented would have been the harshest number in
    # the demo and the easiest for a mentor to disprove.
    bounce_charge_inr: int = 0
    bounce_charge_note: str = "Nil: waived for first-attempt friction under the hardship policy"
    # The context that turns a frightening letter into a solvable problem. 96% is the
    # dataset's own framing of a 0.9591 first-attempt success rate.
    on_time_rate_percent: float = 96.0
    first_attempt_success_rate: float = 0.9591
    history_months: int = 6
    # Why it bounced: three days of market closure cut takings by about 40%.
    root_cause: str = "TEMPORARY_FRICTION"
    dip_days: tuple[str, ...] = ("2026-11-14", "2026-11-15", "2026-11-16")
    hardship_pauses_used_in_window: int = 0

    def as_dict(self) -> dict:
        return {
            "mandate_id": self.mandate_id,
            "amount_inr": self.amount_inr,
            "status": self.status,
            "bounce_date": self.bounce_date,
            "bounce_reason": self.bounce_reason,
            "bounce_charge_inr": self.bounce_charge_inr,
            "bounce_charge_note": self.bounce_charge_note,
            "on_time_rate_percent": self.on_time_rate_percent,
            "first_attempt_success_rate": self.first_attempt_success_rate,
            "history_months": self.history_months,
            "root_cause": self.root_cause,
            "dip_days": list(self.dip_days),
            "hardship_pauses_used_in_window": self.hardship_pauses_used_in_window,
        }


@dataclass
class SalesPattern:
    """What the merchant's own trading history shows. Used for advisory only."""

    avg_daily_sales_inr: int = 32_000
    weekend_multiplier: float = 2.3
    busiest_days: tuple[str, ...] = ("Friday", "Saturday", "Sunday")
    restock_by: str = "Thursday"
    months: int = 6

    def as_dict(self) -> dict:
        return {
            "avg_daily_sales_inr": self.avg_daily_sales_inr,
            "weekend_multiplier": self.weekend_multiplier,
            "busiest_days": list(self.busiest_days),
            "restock_by": self.restock_by,
            "months": self.months,
        }


# There is no pre-approved new facility in the canonical dataset, so this service does
# not invent one. The advisory intent talks about the merchant's own trading and the
# loan they already have, whose real terms are in Loan below.


@dataclass
class Connector:
    """A data source the merchant has consented to, inside the Paytm for Business app.

    We hold the consent STATE only. The contract is explicit that the connectors live on
    the merchant side (8003) and that Paytm never reads their contents, so there is
    deliberately no payload field here: the ledger can report that consent was granted
    without this service ever touching the merchant's Shiprocket or Vyapar data.
    """

    key: str
    state: str  # ACTIVE
    consent: str  # GRANTED | DENIED

    def as_dict(self) -> dict:
        return {"key": self.key, "state": self.state, "consent": self.consent}


CONNECTORS: tuple[Connector, ...] = (
    Connector("SHIPROCKET_SYNC", "ACTIVE", "GRANTED"),
    Connector("VYAPAR_POS_SYNC", "ACTIVE", "GRANTED"),
    Connector("ACTIVE_LOAN_KFS", "ACTIVE", "GRANTED"),
)


@dataclass
class Loan:
    edi_per_day_inr: int = 500
    balance_inr: int = 42_000
    # A literal, not a computed "next business day": today IS 2026-11-19, so a computed
    # date would pass today and quietly break tomorrow.
    next_deduction_date: str = "2026-11-19"

    # Real terms from the canonical dataset, so nothing about this loan is invented.
    loan_id: str = "CLX-ML-26-008821"
    nbfc: str = NBFC_NAME
    sanctioned_inr: int = 115_000
    apr_percent: float = 31.89
    collected_so_far_inr: int = 85_000
    # "collected by eNACH from the merchant's bank account at 07:00, not netted from
    # settlements". Recorded because it is how the loan actually works, even though the
    # contract's projected-payout arithmetic nets it off; see cashflow.py.
    collection_method: str = "Daily eNACH auto-debit on the merchant's bank account"
    edi_holiday_eligible: bool = True
    kfs_clause: str = KFS_CLAUSE
    max_pause_days: int = KFS_MAX_PAUSE_DAYS

    # ACTIVE until a consented pause is executed, then PAUSED_<n>_DAYS.
    status: str = "ACTIVE"
    paused_days: int = 0
    resume_date: str | None = None
    # The KFS consent record for a pause, kept because it is the evidence that the
    # merchant agreed to a change in their credit terms.
    consent_artifact: dict | None = None

    @property
    def edi_due_tomorrow_inr(self) -> int:
        """Nothing comes out of tomorrow's settlement while the EDI is paused."""
        return 0 if self.status != "ACTIVE" else self.edi_per_day_inr

    def as_dict(self) -> dict:
        return {
            "edi_per_day_inr": self.edi_per_day_inr,
            "balance_inr": self.balance_inr,
            "next_deduction_date": self.next_deduction_date,
            "loan_id": self.loan_id,
            "nbfc": self.nbfc,
            "sanctioned_inr": self.sanctioned_inr,
            "apr_percent": self.apr_percent,
            "collected_so_far_inr": self.collected_so_far_inr,
            "collection_method": self.collection_method,
            "edi_holiday_eligible": self.edi_holiday_eligible,
            "kfs_clause": self.kfs_clause,
            "max_pause_days": self.max_pause_days,
            "status": self.status,
            "paused_days": self.paused_days,
            "resume_date": self.resume_date,
            "edi_tomorrow": self.edi_due_tomorrow_inr,
            "consent_artifact": self.consent_artifact,
        }


@dataclass
class Chargeback:
    txn_id: str = "9981"
    order_id: str = "9981"
    amount_held_inr: int = 800
    deadline_iso: str = ""
    hold_status: str = "HELD"  # HELD | RELEASED
    evidence_status: str = "NONE"  # NONE | SUBMITTED

    def as_dict(self) -> dict:
        # hours_left is deliberately computed on read, never stored: a stored value goes
        # stale between chargeback step 1 and step 2.
        return {
            "txn_id": self.txn_id,
            "order_id": self.order_id,
            "amount_held_inr": self.amount_held_inr,
            "deadline_iso": self.deadline_iso,
            "hours_left": round(clock.hours_until(self.deadline_iso), 2),
            "hold_status": self.hold_status,
            "evidence_status": self.evidence_status,
        }


@dataclass
class Ledger:
    mid: str
    merchant_name: str
    gst_registered: bool
    settlement_date: str
    gross_inr: int
    net_credit_inr: int
    soundbox_rental_inr: int
    mdr_bands: tuple[MdrBand, ...]
    orders: dict[str, Order]
    utrs: dict[str, UpiTxn]
    loan: Loan
    chargeback: Chargeback
    mandate: Mandate = field(default_factory=Mandate)
    sales: SalesPattern = field(default_factory=SalesPattern)
    connectors: tuple[Connector, ...] = CONNECTORS
    projected_gross_tomorrow_inr: int = PROJECTED_GROSS_TOMORROW_INR

    # --- derived money ----------------------------------------------------------------
    @property
    def mdr_total_inr(self) -> int:
        return sum(b.fee_inr for b in self.mdr_bands)

    @property
    def gst_on_mdr_inr(self) -> int:
        return int(round(self.mdr_total_inr * GST_RATE_PERCENT / 100))

    @property
    def refund_line_inr(self) -> int:
        """Only refunds that were part of the settlement that has already run."""
        return sum(o.refund_amount_inr or 0 for o in self.orders.values()
                   if o.refund_status == "PROCESSED" and o.in_settlement)

    def duplicate_payments(self) -> list[tuple[str, list[UpiTxn]]]:
        """Orders paid for more than once, oldest payment first.

        A duplicate is read off the ledger rather than guessed: two settled payments
        against one order id is a fact, not an inference.
        """
        by_order: dict[str, list[UpiTxn]] = {}
        for txn in self.utrs.values():
            if txn.order_id and txn.lookup_status == "SUCCESS_SETTLED":
                by_order.setdefault(txn.order_id, []).append(txn)
        return [
            (order_id, sorted(txns, key=lambda t: t.received_at or ""))
            for order_id, txns in by_order.items()
            if len(txns) > 1
        ]

    @property
    def lines(self) -> list[dict]:
        """This service's explanation of the gap between gross and net."""
        refund_order = next((o.order_id for o in self.orders.values()
                             if o.refund_status == "PROCESSED"), "")
        return [
            {"code": "MDR_FEE", "label": "Payment fees", "amount_inr": self.mdr_total_inr},
            {"code": "GST_ON_MDR", "label": "GST on fees", "amount_inr": self.gst_on_mdr_inr},
            {"code": "CUSTOMER_REFUND", "label": f"Refund for order {refund_order}",
             "amount_inr": self.refund_line_inr},
            {"code": "SOUNDBOX_RENTAL", "label": "Soundbox rental",
             "amount_inr": self.soundbox_rental_inr},
            {"code": "CHARGEBACK_HOLD",
             "label": f"Held for dispute on order {self.chargeback.order_id}",
             "amount_inr": self.chargeback.amount_held_inr},
        ]

    @property
    def variance_inr(self) -> int:
        """The gap the merchant is asking about. A fact: gross minus what the bank paid."""
        return self.gross_inr - self.net_credit_inr

    @property
    def lines_total_inr(self) -> int:
        return sum(line["amount_inr"] for line in self.lines)

    @property
    def reconciles(self) -> bool:
        """Do our deductions actually explain the gap? If not, a human must look."""
        return self.lines_total_inr == self.variance_inr

    @property
    def pending_refund_inr(self) -> int:
        """Refunds asked for but not yet taken out of a settlement."""
        return sum(o.refund_amount_inr or 0 for o in self.orders.values()
                   if o.refund_status == "PENDING")

    def projected_net_payout_inr(self) -> int:
        """What tomorrow's payout looks like once the pending refund and EDI come out.

        Derived rather than seeded, so both remedies visibly move it: pausing the EDI
        keeps the daily instalment, and winning a dispute returns the held amount.
        """
        released = (self.chargeback.amount_held_inr
                    if self.chargeback.hold_status == "RELEASED" else 0)
        return (self.projected_gross_tomorrow_inr
                - self.pending_refund_inr
                - self.loan.edi_due_tomorrow_inr
                + released)

    def settlement_as_dict(self) -> dict:
        return {
            "settlement_date": self.settlement_date,
            "gross_inr": self.gross_inr,
            "net_credit_inr": self.net_credit_inr,
            "variance_inr": self.variance_inr,
            "lines": self.lines,
            "lines_total_inr": self.lines_total_inr,
            "reconciles": self.reconciles,
        }

    def as_dict(self) -> dict:
        return {
            "mid": self.mid,
            "merchant_name": self.merchant_name,
            "gst_registered": self.gst_registered,
            "settlement": self.settlement_as_dict(),
            "mdr_breakdown": [b.as_dict() for b in self.mdr_bands],
            "orders": [o.as_dict() for o in self.orders.values()],
            "transactions": [t.as_dict() for t in self.utrs.values()],
            "loan": self.loan.as_dict(),
            "chargeback": self.chargeback.as_dict(),
            # Named exactly as the V2 delta asks for it, alongside the fuller loan object.
            "loan_edi_status": self.loan.status,
            "mandate": self.mandate.as_dict(),
            "sales": self.sales.as_dict(),
            "connectors": [c.as_dict() for c in self.connectors],
            "projected_net_payout_inr": self.projected_net_payout_inr(),
        }


def fresh(chargeback_hours_left: float = CHARGEBACK_DEFAULT_HOURS,
          break_settlement: bool = False) -> Ledger:
    """Build a clean ledger.

    `break_settlement` perturbs one deduction so the lines no longer add up to the
    variance. Without this lever the SETTLEMENT_UNRECONCILED escalation path has no
    trigger and could never be tested or demonstrated.
    """
    rental = SOUNDBOX_RENTAL_INR + (100 if break_settlement else 0)

    return Ledger(
        mid=MID,
        merchant_name=MERCHANT_NAME,
        gst_registered=GST_REGISTERED,
        settlement_date=SETTLEMENT_DATE,
        gross_inr=GROSS_SALES_INR,
        net_credit_inr=NET_BANK_CREDIT_INR,
        soundbox_rental_inr=rental,
        mdr_bands=MDR_BANDS,
        orders={
            # Already refunded, and that refund is one of the settlement deductions.
            "4412": Order("4412", amount_inr=1_500, settled=True,
                          refund_status="PROCESSED", refund_amount_inr=1_500,
                          in_settlement=True),
            # The V2 delta's cashflow case: a refund asked for but not yet taken, which
            # is what squeezes tomorrow's payout. PENDING, so it does not appear in
            # yesterday's settlement lines.
            "4490": Order("4490", amount_inr=3_500, settled=True,
                          refund_status="PENDING", refund_amount_inr=3_500),
            # Paid for twice. Order, amount and both references come from the canonical
            # dataset (data/seed/utr_ledger.csv, flagged DUPLICATE), replacing an
            # earlier pair of our own invention.
            "4489": Order("4489", amount_inr=1_180, settled=True, refund_status="NONE"),
        },
        utrs={
            "632184920111": UpiTxn("632184920111", 1_250, "GPay", "SUCCESS_SETTLED",
                                   order_id="BILL-261118-0011",
                                   received_at="2026-11-18T11:03:14+00:00"),
            "632184920999": UpiTxn("632184920999", 2_400, "PhonePe", "PENDING",
                                   order_id="BILL-261118-0018",
                                   received_at="2026-11-18T18:15:40+00:00"),
            # One order, two settled payments 48 seconds apart: what a customer tapping
            # twice on a slow connection looks like.
            "632299206882": UpiTxn("632299206882", 1_180, "PhonePe", "SUCCESS_SETTLED",
                                   order_id="4489",
                                   received_at="2026-11-18T19:42:10+00:00"),
            "632230725895": UpiTxn("632230725895", 1_180, "PhonePe", "SUCCESS_SETTLED",
                                   order_id="4489",
                                   received_at="2026-11-18T19:42:58+00:00"),
        },
        loan=Loan(),
        chargeback=Chargeback(
            deadline_iso=clock.plus_hours(chargeback_hours_left).isoformat(),
        ),
    )
