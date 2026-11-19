"""The Paytm Master Orchestrator and its four specialist sub-agents.

Every request is worked by the same four, in the same order, each with one job:

  IntelligenceAgent   reads. Parses the request and pulls the relevant facts out of
                      the ledger. Decides nothing.
  RiskPolicyAgent     judges. Applies the policy constants and decides whether the
                      agent may close this alone or a human must take it. Reads
                      nothing new and changes nothing.
  ResolutionAgent     composes. Turns facts and verdict into the remedy and the
                      sentence the merchant hears. Changes nothing.
  LedgerOpsAgent      acts. The only one allowed to mutate the merchant's account.

The split is not decoration. It is the one that makes the service auditable: a question
like "could this agent have moved money?" is answered by looking at whether
LedgerOpsAgent did anything, and "why was this escalated?" is answered by RiskPolicyAgent's
line alone. Each sub-agent reports what it did, and those reports are the `agent_trace`
returned to the caller and shown in the employee console.

A sub-agent with nothing to do still appears in the trace, saying so. "LedgerOpsAgent:
no ledger change required" is a useful thing to be able to prove.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .models import DispatchRequest, IntentResult

# The order is the pipeline: read, judge, compose, act.
AGENT_SEQUENCE = (
    ("IntelligenceAgent", "gather"),
    ("RiskPolicyAgent", "assess"),
    ("ResolutionAgent", "resolve"),
    ("LedgerOpsAgent", "apply"),
)

# What a sub-agent says when its stage does not apply to this intent. Said out loud
# rather than hidden, because "nothing was changed" is evidence.
IDLE_NOTES = {
    "IntelligenceAgent": "Nothing to read for this request",
    "RiskPolicyAgent": "No policy decision needed",
    "ResolutionAgent": "No reply to compose",
    "LedgerOpsAgent": "No ledger change required",
}


@dataclass
class Case:
    """The shared case file the four sub-agents work on, in turn.

    Each stage reads what the previous ones wrote and adds its own part. It ends up
    carrying everything an IntentResult needs.
    """

    req: DispatchRequest
    ledger: Any
    session: Any

    # Filled by IntelligenceAgent.
    data: dict[str, Any] = field(default_factory=dict)

    # Filled by RiskPolicyAgent.
    status: str = "RESOLVED"
    reason_code: Optional[str] = None
    reason_text: str = ""
    urgency: str = "NORMAL"
    deadline_iso: Optional[str] = None
    fraud_event: Optional[dict] = None

    # Filled by ResolutionAgent.
    found: str = ""
    action_taken: str = "None, explained only"
    action_required: Optional[dict] = None
    suggested_next_step: str = ""
    template_text: str = ""
    tried: list[str] = field(default_factory=list)

    @property
    def escalated(self) -> bool:
        return self.status == "ESCALATED"

    def escalate(self, reason_code: str, reason_text: str = "",
                 urgency: str = "NORMAL", deadline_iso: str | None = None) -> None:
        """Only RiskPolicyAgent should call this."""
        self.status = "ESCALATED"
        self.reason_code = reason_code
        self.reason_text = reason_text
        self.urgency = urgency
        self.deadline_iso = deadline_iso


def orchestrate(case: Case, module) -> tuple[IntentResult, list[dict]]:
    """Run the four sub-agents over one case and collect what each of them did.

    An intent module supplies whichever of `gather`, `assess`, `resolve` and `apply` it
    needs; each returns one line describing what it did. A stage the module omits is
    recorded as idle rather than skipped silently.
    """
    trace: list[dict] = []

    for step, (agent, stage) in enumerate(AGENT_SEQUENCE, start=1):
        fn: Callable[[Case], str] | None = getattr(module, stage, None)
        started = time.perf_counter()

        # A PayloadError from any stage propagates to dispatch, which turns it into
        # BAD_PAYLOAD. The trace is dropped with it: a request we could not parse has
        # no story worth telling.
        note = fn(case) if fn is not None else None

        # A stage reports idleness by returning None, either because the module has no
        # such stage or because this particular case gave it nothing to do. That
        # distinction matters: "LedgerOpsAgent did not act" is the claim being made, so
        # it must not be true merely because a function existed and ran.
        acted = note is not None
        if not acted:
            note = IDLE_NOTES[agent]

        trace.append({
            "step": step,
            "agent": agent,
            "acted": acted,
            "note": note,
            "ms": round((time.perf_counter() - started) * 1000, 2),
        })

    result = IntentResult(
        data=case.data,
        status=case.status,
        found=case.found,
        action_taken=case.action_taken,
        template_text=case.template_text,
        action_required=case.action_required,
        reason_code=case.reason_code,
        reason_text=case.reason_text,
        tried=case.tried,
        suggested_next_step=case.suggested_next_step,
        urgency=case.urgency,
        deadline_iso=case.deadline_iso,
        fraud_event=case.fraud_event,
    )
    return result, trace
