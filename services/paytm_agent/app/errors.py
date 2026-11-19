"""The one error shape this service returns (contract section 2.4).

    {"error": {"code": ..., "message": ..., "retryable": false}}

A single helper so no endpoint invents its own shape. Callers (Person 3) branch on
`code`, never on the message text, so messages stay free to be human-readable.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse

# Codes from the contract. UPSTREAM_TIMEOUT is the only retryable one: everything else
# will fail again in exactly the same way, and a retry just costs the merchant time.
RETRYABLE = {"UPSTREAM_TIMEOUT"}

CODES = {
    "CONSENT_MISSING",
    "UNKNOWN_MID",
    "UNKNOWN_INTENT",
    "BAD_PAYLOAD",
    "NOT_FOUND",
    "UPSTREAM_TIMEOUT",
    "INTERNAL",
    # From the V2 delta. Two consent conventions now coexist in this service, which is
    # not pretty but is what the contract specifies: /a2a/dispatch answers a missing
    # token with 400 CONSENT_MISSING, while /a2a/execute-edi-pause must answer 403
    # DPDP_CONSENT_REQUIRED. Person 3 branches on the code, so both are honoured.
    "DPDP_CONSENT_REQUIRED",
    "EDI_PAUSE_NOT_ELIGIBLE",
}


class PayloadError(Exception):
    """An intent handler was given a payload it cannot work with.

    Raised by handlers (which are otherwise pure) and turned into the contract's
    BAD_PAYLOAD error by dispatch, so no handler has to know about HTTP.
    """


def error_body(code: str, message: str) -> dict:
    assert code in CODES, f"{code} is not a contract error code"
    return {"error": {"code": code, "message": message, "retryable": code in RETRYABLE}}


def error_response(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message))
