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


# Chosen so the bands add up to the 1,450 the contract quotes.
MDR_BANDS: tuple[MdrBand, ...] = (
    MdrBand("Credit card", 45_000, 2.0),
    MdrBand("Wallet-on-UPI above 2000", 50_000, 1.1,
            note="(assumption) rate taken from one third-party note, not a Paytm schedule"),
    MdrBand("Bank UPI", 5_000, 0.0, note="zero MDR on bank-to-bank UPI"),
)


@dataclass
class Order:
    order_id: str
    amount_inr: int
    settled: bool
    refund_status: str  # NONE | PENDING | PROCESSED
    refund_amount_inr: int | None = None

    def as_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "amount_inr": self.amount_inr,
            "settled": self.settled,
            "refund_status": self.refund_status,
            "refund_amount_inr": self.refund_amount_inr,
        }


@dataclass
class UpiTxn:
    utr: str
    amount_inr: int
    payer_app: str
    lookup_status: str  # SUCCESS_SETTLED | PENDING

    def as_dict(self) -> dict:
        return {
            "utr": self.utr,
            "amount_inr": self.amount_inr,
            "payer_app": self.payer_app,
            "lookup_status": self.lookup_status,
        }


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

    nbfc: str = NBFC_NAME
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
            "nbfc": self.nbfc,
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
        return sum(o.refund_amount_inr or 0 for o in self.orders.values()
                   if o.refund_status == "PROCESSED")

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

        Derived rather than seeded, so pausing the EDI visibly moves it.
        """
        return (self.projected_gross_tomorrow_inr
                - self.pending_refund_inr
                - self.loan.edi_due_tomorrow_inr)

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
                          refund_status="PROCESSED", refund_amount_inr=1_500),
            # The V2 delta's cashflow case: a refund asked for but not yet taken, which
            # is what squeezes tomorrow's payout. PENDING, so it does not appear in
            # yesterday's settlement lines.
            "4490": Order("4490", amount_inr=3_500, settled=True,
                          refund_status="PENDING", refund_amount_inr=3_500),
        },
        utrs={
            "632184920111": UpiTxn("632184920111", 1_250, "GPay", "SUCCESS_SETTLED"),
            "632184920999": UpiTxn("632184920999", 2_400, "PhonePe", "PENDING"),
        },
        loan=Loan(),
        chargeback=Chargeback(
            deadline_iso=clock.plus_hours(chargeback_hours_left).isoformat(),
        ),
    )
