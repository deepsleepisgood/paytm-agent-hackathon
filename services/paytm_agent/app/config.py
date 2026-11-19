"""Runtime configuration and the frozen decision constants.

Two kinds of value live here, and only here:

1. Decision constants from the contract (section 2.1). These are ASSUMPTIONS to confirm
   with the Paytm mentor, not verified Paytm policy. They exist in exactly one place so
   that the demo, the tests and the pitch can never disagree about them. If you find
   yourself typing 0.90 or 2000 anywhere else in this service, import it from here.

2. Deployment settings read from the environment. Nothing is hard-coded to localhost:
   the product needs a live link, and a URL baked into Python is how that gets missed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# --- Frozen decision constants (contract section 2.1) ----------------------------------
# Minimum document confidence to act without a human. Below this we escalate rather than
# submit evidence, because wrong evidence can lose the dispute outright.
AUTO_DOC_CONFIDENCE = 0.90

# Largest refund (INR) the agent may approve alone. Above this, money leaving Paytm is a
# human's decision.
REFUND_AUTO_LIMIT_INR = 2000

# A chargeback deadline closer than this many hours, with no usable proof, is urgent:
# a human can chase the merchant by phone, the agent cannot.
URGENT_HOURS = 12

# Unknown UTRs in one session before we stop answering and escalate. Repeated unknown
# payments in a single conversation is the shape of a fraud attempt against the merchant.
UNKNOWN_UTR_LIMIT = 3

# Largest duplicate payment (INR) the agent may return to a customer alone. Higher than
# REFUND_AUTO_LIMIT_INR on purpose: a discretionary refund is a judgement call, whereas a
# duplicate is a provable double charge — the ledger shows two settled payments against
# one order, so there is nothing to decide. sarvam_service's own Hindi reply quotes this
# same 5,000 figure, so the two services tell the merchant the same story.
DUPLICATE_AUTO_LIMIT_INR = 5000

# Hardship pauses a merchant may take in a rolling 90 days before a human must look.
# (assumption) Not a published Paytm or NBFC rule.
HARDSHIP_PAUSE_WINDOW_DAYS = 90
HARDSHIP_PAUSES_PER_WINDOW = 1


def _origins() -> tuple[str, ...]:
    """CORS origins.

    The contract calls this ALLOWED_ORIGINS; Person 1's service calls it CORS_ORIGINS.
    We accept either so neither teammate has to rename anything mid-hackathon.
    """
    raw = os.getenv("ALLOWED_ORIGINS") or os.getenv("CORS_ORIGINS") or (
        "http://localhost:3000,http://127.0.0.1:3000"
    )
    return tuple(o.strip() for o in raw.split(",") if o.strip())


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8002")))
    cors_origins: tuple[str, ...] = field(default_factory=_origins)

    # The merchant this demo is seeded for. Any other mid is UNKNOWN_MID.
    seed_mid: str = field(default_factory=lambda: os.getenv("SEED_MID", "PAYTM_MERCH_8821"))


settings = Settings()
