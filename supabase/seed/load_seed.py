#!/usr/bin/env python3
"""Load data/seed (merchant side) and data/paytm (Paytm side) into Supabase Postgres.

    SUPABASE_DB_URL='postgresql://postgres.<ref>:<db-password>@aws-0-ap-south-1.pooler.supabase.com:5432/postgres' \
        python supabase/seed/load_seed.py            # load + snapshot + reset + verify
    python supabase/seed/load_seed.py --verify-only  # just compare the DB with ledger_initial_state.json

* Idempotent: one transaction truncates every table in the `paytm` and `merchant` schemas and reloads them,
  so a failed run leaves the previous data untouched.
* Naive timestamps in the CSVs are IST (the session time zone is set to Asia/Kolkata).
* Needs the *owner* connection (the `postgres` user from Dashboard -> Connect). The services never use it;
  they connect as `paytm_svc` / `merchant_svc`. Never commit the URL.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed"
PAYTM = ROOT / "data" / "paytm"
MID = "PAYTM_MERCH_8821"
NULLS = {"", "NaT", "nan", "NaN", "None", "null"}


# ----------------------------------------------------------------------------- helpers
def csv(path: Path, rename: dict | None = None, **const) -> list[dict]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if rename:
        df = df.rename(columns=rename)
    rows = df.to_dict("records")
    for r in rows:
        r.update(const)
    return rows


def js(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pg_array(v) -> str:
    def q(x):
        s = str(x).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    return "{" + ",".join(q(x) for x in v) + "}"


def coerce(value, pg_type: str):
    """Turn a CSV/JSON value into the text form Postgres expects for COPY."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if pg_type == "jsonb":
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if pg_type == "ARRAY":
        if isinstance(value, str):
            value = json.loads(value) if value.startswith("[") else [value]
        return _pg_array(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    s = str(value).strip()
    if s in NULLS:
        return None
    if pg_type in ("integer", "bigint", "smallint"):
        return str(int(round(float(s))))           # csat "5.0" -> 5
    if pg_type == "boolean":
        return {"true": "t", "false": "f", "1": "t", "0": "f", "yes": "t", "no": "f"}[s.lower()]
    return s


class Loader:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self.cols: dict[str, dict[str, str]] = {}
        self.counts: dict[str, int] = {}
        self.dropped: dict[str, set[str]] = {}
        with conn.cursor() as cur:
            cur.execute("""select table_schema||'.'||table_name, column_name, data_type, is_generated, is_identity
                           from information_schema.columns where table_schema in ('paytm','merchant')
                           order by ordinal_position""")
            for t, c, typ, gen, ident in cur.fetchall():
                if gen == "NEVER" and ident == "NO":
                    self.cols.setdefault(t, {})[c] = "ARRAY" if typ == "ARRAY" else typ

    def copy(self, table: str, rows: list[dict]):
        if not rows:
            raise SystemExit(f"no rows for {table}")
        tcols = self.cols[table]
        present = [c for c in tcols if any(c in r for r in rows)]
        extra = {k for r in rows for k in r} - set(tcols)
        if extra:
            self.dropped[table] = extra
        with self.conn.cursor() as cur:
            with cur.copy(f"copy {table} ({', '.join(present)}) from stdin") as cp:
                for r in rows:
                    cp.write_row([coerce(r.get(c), tcols[c]) for c in present])
        self.counts[table] = len(rows)


# ----------------------------------------------------------------------------- merchant side
def merchant_rows() -> list[tuple[str, list[dict]]]:
    p = js(SEED / "merchant_profile.json")
    hm, st, ad = p["historical_memory"], p["settlement"], p["address"]
    profile = [{
        "mid": p["mid"], "name": p["name"], "owner": p["owner"], "category": p["category"], "mcc": p["mcc"],
        "kyc_tier": p["kyc_tier"], "gstin": p["gstin"], "address_line1": ad["line1"], "city": ad["city"],
        "state": ad["state"], "pincode": ad["pincode"], "store_hours": p["store_hours"],
        "onboarded_on": p["onboarded_on"], "settlement_cycle": st["cycle"], "bank_masked": st["bank"],
        "ifsc": st["ifsc"], "as_of": p["as_of"], **hm}]
    connectors = [{"mid": p["mid"], **c} for c in p["connectors"]]

    loan = js(SEED / "loan.json")
    m_loan = [{**loan, "apr_percent": loan["kfs"]["apr_percent"], "mandate_umrn": loan["mandate"]["umrn"],
               "kfs_clauses": loan["kfs"]["clauses"]}]

    sb = js(SEED / "settlement_breakdown_2026-11-18.json")
    deductions = [{"batch_id": sb["batch_id"], **d} for d in sb["deductions"]]

    orders = js(SEED / "shiprocket_orders.json")["orders"]
    shipments = [{k: v for k, v in o.items() if k not in ("items", "pod")} for o in orders]
    items = [{"order_id": o["order_id"], **i} for o in orders for i in o["items"]]
    pods = [{"order_id": o["order_id"], **o["pod"]} for o in orders if o.get("pod")]

    sm = js(SEED / "strategy_memory.json")
    memories = [{**m, "seeded": True} for m in sm["memories"]]
    scen = [{"intent": s["intent"], "body": s} for s in js(SEED / "scenarios.json")["scenarios"]]
    state = [{"key": "loan_edi_status", "value": "ACTIVE"},
             {"key": "learned_policies", "value": json.dumps(sm["learned_policies"], ensure_ascii=False)}]

    return [
        ("merchant.profile", profile),
        ("merchant.connectors", connectors),
        ("merchant.customers", csv(SEED / "customers.csv")),
        ("merchant.transactions", csv(SEED / "transactions.csv", {"timestamp": "ts"})),
        ("merchant.daily_sales", csv(SEED / "daily_sales_summary.csv")),
        ("merchant.settlements", csv(SEED / "settlements.csv")),
        ("merchant.settlement_deductions", deductions),
        ("merchant.loan", m_loan),
        ("merchant.edi_schedule", csv(SEED / "edi_schedule.csv")),
        ("merchant.refunds", csv(SEED / "refunds.csv")),
        ("merchant.chargebacks", csv(SEED / "chargebacks.csv")),
        ("merchant.shipments", shipments),
        ("merchant.shipment_items", items),
        ("merchant.pods", pods),
        ("merchant.utr_ledger", csv(SEED / "utr_ledger.csv", {"timestamp": "ts"})),
        ("merchant.supplier_payables", csv(SEED / "supplier_payables.csv")),
        ("merchant.khata", csv(SEED / "khata.csv", {"timestamp": "ts"}, seeded=True)),
        ("merchant.inventory", csv(SEED / "inventory.csv")),
        ("merchant.device_logs", csv(SEED / "device_logs.csv")),
        ("merchant.support_history", csv(SEED / "support_history.csv")),
        ("merchant.strategy_memory", memories),
        ("merchant.scenarios", scen),
        ("merchant.agent_state", state),
    ]


# ----------------------------------------------------------------------------- paytm side
def paytm_rows() -> list[tuple[str, list[dict]]]:
    cbs = csv(PAYTM / "chargebacks.csv")
    history = [{"case_id": c["case_id"], "ts": h["ts"], "status": h["status"], "actor": h.get("by"),
                "note": h.get("note"), "seeded": True}
               for c in cbs for h in json.loads(c["status_history"] or "[]")]

    pod = js(PAYTM / "connectors" / "shiprocket_pod.json")
    pods = [{**{k: v for k, v in pod.items() if k not in ("pod", "document")}, **pod["pod"],
             "document_path": pod["document"]["path"], "document_sha256": pod["document"]["sha256"]}]

    lb = js(PAYTM / "lending" / "loan_book.json")
    loan_book = [{**lb, "edi_status": "ACTIVE",
                  "kfs_markdown": (PAYTM / "lending" / "kfs_document.md").read_text(encoding="utf-8")}]

    mdr = js(PAYTM / "mdr_rate_card.json")
    rates = [{"tier": t, "method": m, "rate_percent": r}
             for t, ms in mdr["rates_percent"].items() for m, r in ms.items()]
    policies = [{"name": f.stem, "body": js(f)} for f in sorted((PAYTM / "policies").glob("*.json"))]
    policies += [{"name": "lender_policies", "body": js(PAYTM / "lending" / "lender_policies.json")},
                 {"name": "mdr_rate_card", "body": mdr}]
    scen = [{"intent": s["intent"], "body": s} for s in js(PAYTM / "scenarios_paytm.json")["scenarios"]]
    counters = [{"name": n, "value": 0}
                for n in ("outcomes_verified", "tickets_deflected", "fraud_blocked", "money_recovered_inr")]

    return [
        ("paytm.merchant_master", csv(PAYTM / "merchant_master.csv")),
        ("paytm.acquiring_ledger", csv(PAYTM / "acquiring_ledger.csv", {"timestamp": "ts"})),
        ("paytm.npci_utr_log", csv(PAYTM / "npci_utr_log.csv")),
        ("paytm.settlement_batches", csv(PAYTM / "settlement_batches.csv")),
        ("paytm.settlement_lines", csv(PAYTM / "settlement_lines_2026-11-18.csv")),
        ("paytm.mdr_rates", rates),
        ("paytm.policies", policies),
        ("paytm.chargebacks", cbs),
        ("paytm.chargeback_status_history", history),
        ("paytm.shiprocket_pods", pods),
        ("paytm.refunds", csv(PAYTM / "refunds.csv", seeded=True)),
        ("paytm.loan_book", loan_book),
        ("paytm.enach_mandates", csv(PAYTM / "lending" / "enach_mandates.csv")),
        ("paytm.edi_collections", csv(PAYTM / "lending" / "edi_collections.csv", seeded=True)),
        ("paytm.risk_scores", csv(PAYTM / "risk" / "merchant_risk_scores.csv")),
        ("paytm.fraud_signals", csv(PAYTM / "risk" / "fraud_signals.csv", seeded=True)),
        ("paytm.soundbox_fleet", csv(PAYTM / "devices" / "soundbox_fleet.csv")),
        ("paytm.soundbox_telemetry", csv(PAYTM / "devices" / "soundbox_telemetry.csv")),
        ("paytm.tickets", csv(PAYTM / "support" / "tickets.csv", seeded=True)),
        ("paytm.dpdp_consents", csv(PAYTM / "consent" / "dpdp_consents.csv", seeded=True)),
        ("paytm.outcome_history", csv(PAYTM / "learning" / "outcome_history.csv")),
        ("paytm.scenarios", scen),
        ("paytm.initial_state", [{"id": 1, "body": js(PAYTM / "ledger_initial_state.json")}]),
        ("paytm.demo_counters", counters),
    ]


# ----------------------------------------------------------------------------- verification
def db_state(conn: psycopg.Connection) -> dict:
    """The live demo state, in the same shape as data/paytm/ledger_initial_state.json."""
    q = lambda sql, *a: conn.execute(sql, a).fetchone()  # noqa: E731
    s = q("select batch_id, gross, net_credit, variance from paytm.settlement_batches "
          "where mid=%s and settlement_date='2026-11-18'", MID)
    loan = q("select edi_status::text, daily_edi, outstanding, overdue_amount, dpd from paytm.loan_book where mid=%s", MID)
    mandate = q("select status::text from paytm.enach_mandates where mid=%s", MID)
    cb = q("select status::text, round(extract(epoch from paytm_evidence_due - now())/3600) "
           "from paytm.chargebacks where chargeback_id='CB-9981'")
    refunds = dict(conn.execute("select refund_id, status::text from paytm.refunds "
                                "where refund_id in ('RFD-4412','RFD-4490','RFD-DUP-4489')").fetchall())
    utrs = dict(conn.execute("select utr, status::text from paytm.npci_utr_log where utr = any(%s)",
                             (["632184920111", "632184920999", "632299206882", "632230725895"],)).fetchall())
    fake = q("select count(*) from paytm.npci_utr_log where utr='632184920555'")[0]
    counters = dict(conn.execute("select name, value from paytm.demo_counters").fetchall())
    nxt = q("select last_value + case when is_called then 1 else 0 end from paytm.ticket_seq")[0]
    audit = q("""select (select count(*) from paytm.consent_checks)+(select count(*) from paytm.utr_checks)
                 +(select count(*) from paytm.agent_trace)+(select count(*) from paytm.verified_outcomes)
                 +(select count(*) from paytm.pending_credits)+(select count(*) from paytm.upi_collect_links)
                 +(select count(*) from paytm.lender_approvals)+(select count(*) from paytm.kfs_consent_artifacts)
                 +(select count(*) from merchant.a2a_events)+(select count(*) from merchant.gst_itc_log)""")[0]
    m_edi = q("select value from merchant.agent_state where key='loan_edi_status'")[0]
    return {"settlement": {"batch_id": s[0], "gross": s[1], "net_credit": s[2], "variance": s[3]},
            "loan": {"edi_status": loan[0], "daily_edi": loan[1], "outstanding": loan[2],
                     "overdue_amount": loan[3], "dpd": loan[4]},
            "mandate": {"status": mandate[0]}, "chargeback_9981": {"status": cb[0], "hours_left": int(cb[1])},
            "refunds": refunds, "utrs": utrs, "fake_utr_rows": fake, "counters": counters,
            "next_ticket_id": f"TKT-PAYTM-{nxt}", "audit_rows": audit, "merchant_loan_edi_status": m_edi}


def verify(conn: psycopg.Connection) -> list[str]:
    """Compare the DB with ledger_initial_state.json. Returns a list of mismatches (empty = OK)."""
    want = js(PAYTM / "ledger_initial_state.json")
    got = db_state(conn)
    utr_map = {"SUCCESS_SETTLED": "SUCCESS"}
    checks = [
        ("settlement.batch_id", got["settlement"]["batch_id"], want["settlement"]["batch_id"]),
        ("settlement.gross", got["settlement"]["gross"], want["settlement"]["gross"]),
        ("settlement.net_credit", got["settlement"]["net_credit"], want["settlement"]["net_credit"]),
        ("settlement.variance", got["settlement"]["variance"], want["settlement"]["variance"]),
        *[(f"loan.{k}", got["loan"][k], want["loan"][k])
          for k in ("edi_status", "daily_edi", "outstanding", "overdue_amount", "dpd")],
        ("mandate.status", got["mandate"]["status"], want["mandate"]["status"]),
        ("chargebacks.CB-9981.status", got["chargeback_9981"]["status"], want["chargebacks"]["CB-9981"]["status"]),
        ("chargebacks.CB-9981.hours_left>0", got["chargeback_9981"]["hours_left"] > 0, True),
        ("refunds", got["refunds"], want["refunds"]),
        *[(f"utrs.{u}", got["utrs"].get(u), utr_map.get(v["status"], v["status"])) for u, v in want["utrs"].items()],
        ("unknown utr absent", got["fake_utr_rows"], 0),
        ("counters", got["counters"], want["counters"]),
        ("next_ticket_id", got["next_ticket_id"], want["next_ticket_id"]),
        ("audit tables empty", got["audit_rows"], 0),
        ("merchant loan_edi_status", got["merchant_loan_edi_status"], want["loan"]["edi_status"]),
    ]
    return [f"{name}: db={g!r} expected={w!r}" for name, g, w in checks if g != w]


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-url", default=os.getenv("SUPABASE_DB_URL"))
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()
    if not a.db_url:
        print("Set SUPABASE_DB_URL (owner connection string) or pass --db-url", file=sys.stderr)
        return 2

    with psycopg.connect(a.db_url, autocommit=False, prepare_threshold=None) as conn:
        conn.execute("set timezone = 'Asia/Kolkata'")
        if not a.verify_only:
            t0 = time.perf_counter()
            ld = Loader(conn)
            plan = merchant_rows() + paytm_rows()
            conn.execute("truncate " + ", ".join(sorted(ld.cols)) + " restart identity cascade")
            for table, rows in plan:
                ld.copy(table, rows)
            snap = conn.execute("select paytm.take_snapshot()").fetchone()[0]
            p = conn.execute("select paytm.reset_demo()").fetchone()[0]
            m = conn.execute("select merchant.reset_demo()").fetchone()[0]
            conn.commit()
            for t, n in ld.counts.items():
                print(f"  {t:<34} {n:>6}")
            for t, cols in ld.dropped.items():
                print(f"  (not stored) {t}: {', '.join(sorted(cols))}")
            print(f"loaded {sum(ld.counts.values())} rows into {len(ld.counts)} tables "
                  f"in {time.perf_counter() - t0:.1f}s; snapshot {snap}; reset {p['ms']}ms + {m['ms']}ms")
        problems = verify(conn)
        conn.rollback()
    if problems:
        print("VERIFY FAILED:\n  " + "\n  ".join(problems))
        return 1
    print("VERIFY OK: database matches data/paytm/ledger_initial_state.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
