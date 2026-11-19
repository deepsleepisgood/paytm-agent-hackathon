"""One module per intent, each worked by the four sub-agents in mesh.py.

A module supplies whichever of these it needs, and each returns one line saying what it
did, which becomes that sub-agent's entry in the agent_trace:

    gather(case)   IntelligenceAgent   read the request and the ledger
    assess(case)   RiskPolicyAgent     decide: close it, or hand it to a human
    resolve(case)  ResolutionAgent     compose the remedy and the merchant's sentence
    apply(case)    LedgerOpsAgent      change the merchant's account

A stage a module leaves out is reported as idle rather than skipped quietly, so
"LedgerOpsAgent: no ledger change required" is something the trace can prove.
"""
from __future__ import annotations

from . import chargeback, escalate, settlement, utr

MODULES = {
    "SETTLEMENT_RECONCILE": settlement,
    "UTR_VERIFY": utr,
    "CHARGEBACK_RESOLVE": chargeback,
    "ESCALATE_HUMAN": escalate,
}
