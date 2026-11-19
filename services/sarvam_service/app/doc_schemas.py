"""What we ask Sarvam Vision to pull out of each document type, and how we check it.

Sarvam's Extract API takes a JSON schema where every field has a `type` and a
`description`. The description is effectively the prompt for that field, so it says
where the value usually sits on the page and what format we want back.
"""
from __future__ import annotations

from typing import Any

# --- UPI payment screenshot (used by UTR_VERIFY) -------------------------------------
UPI_SCREENSHOT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "utr": {
            "type": "string",
            "description": "UPI transaction reference number (UTR / UPI Ref No / UPI transaction ID). "
            "Usually 12 digits. Digits only, no spaces.",
        },
        "amount": {
            "type": "number",
            "description": "Amount paid in INR as shown on the screen. Number only, no currency symbol or commas.",
        },
        "payer_app": {
            "type": "string",
            "description": "App the screenshot is from, e.g. GPay, PhonePe, Paytm, BHIM, Amazon Pay.",
        },
        "status": {
            "type": "string",
            "enum": ["SUCCESS", "PENDING", "FAILED", "UNKNOWN"],
            "description": "Payment status shown on the screen (Successful/Completed = SUCCESS).",
        },
        "transaction_datetime": {
            "type": "string",
            "description": "Date and time of the payment exactly as printed on the screen.",
        },
        "payee_name": {"type": "string", "description": "Name of the person or shop that was paid."},
        "payee_vpa": {"type": "string", "description": "UPI ID of the payee, e.g. shop@paytm, if visible."},
        "payer_name": {"type": "string", "description": "Name of the person who paid, if visible."},
    },
}
UPI_REQUIRED = ("utr", "amount", "status")

# --- Proof of Delivery (used by CHARGEBACK_RESOLVE) ----------------------------------
POD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order_id": {
            "type": "string",
            "description": "Order number or invoice number on the document. Digits/letters only, without '#'.",
        },
        "awb_or_tracking_id": {
            "type": "string",
            "description": "Courier AWB / tracking / consignment number, if present.",
        },
        "courier_name": {"type": "string", "description": "Courier or delivery company name, if present."},
        "delivery_date": {
            "type": "string",
            "description": "Date the item was delivered, in YYYY-MM-DD format if possible.",
        },
        "recipient_name": {"type": "string", "description": "Name of the person who received the item."},
        "delivery_address": {"type": "string", "description": "Delivery address."},
        "amount": {"type": "number", "description": "Order / invoice amount in INR, number only."},
        "signature_present": {
            "type": "boolean",
            "description": "True if a recipient signature, OTP confirmation or delivery stamp is visible.",
        },
    },
}
POD_REQUIRED = ("order_id", "delivery_date", "recipient_name", "signature_present")

SCHEMAS = {"upi_screenshot": UPI_SCREENSHOT_SCHEMA, "pod": POD_SCHEMA}
REQUIRED = {"upi_screenshot": UPI_REQUIRED, "pod": POD_REQUIRED}
