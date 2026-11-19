"""Person 2 — Paytm AI teammate (port 8002).

This service owns the merchant's ledger, the decision rules, the actions it may take
alone, and the record of every call: summaries for the feed and tickets for the humans.
It also serves the employee console, so there is one thing to deploy and one live link.

Hard rule, enforced by construction: every rupee figure the merchant hears comes from
code reading the seed ledger. No language model runs in this service at all.

Endpoints (contract section 5):
  POST /a2a/dispatch              the one entry point the merchant agent calls
  GET  /ledger/{mid}              full live state
  POST /ledger/reset              reset in-memory state (demo lever)
  GET  /summaries                 call feed, newest first
  GET  /tickets                   escalation queue
  POST /tickets/{id}/claim        an employee takes a ticket
  POST /tickets/{id}/resolve      an employee closes it
  GET  /metrics                   the numbers strip
  GET  /health                    liveness
  GET  /                          the employee console
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import routes_ops
from .config import settings
from .errors import error_body

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("paytm_agent")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Paytm AI Teammate (Person 2)", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(routes_ops.router)


@app.exception_handler(RequestValidationError)
def malformed_body(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Answer a malformed body in the contract's error shape.

    FastAPI's own 422 has a different envelope, so Person 3 would have to special-case
    it. Every failure from this service looks the same: {"error": {code, message, ...}}.
    """
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
    message = f"{where}: {first.get('msg', 'invalid request body')}" if where else "invalid request body"
    return JSONResponse(status_code=400, content=error_body("BAD_PAYLOAD", message))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "paytm_agent"}


@app.get("/")
def console() -> FileResponse:
    """The employee console.

    Served same-origin by this app on purpose: no build step, no second deployment, and
    no CORS between the console and the API it reads.
    """
    return FileResponse(STATIC_DIR / "index.html")
