// Live ledger for the console, straight from Supabase (read-only, anon key + RLS).
//
// Setup (Person 4):
//   cd frontend && npm i @supabase/supabase-js
//   cp ../supabase/frontend/useLedgerRealtime.js src/
//   frontend/.env:  VITE_SUPABASE_URL=https://ijitntwpnqwkjrboweky.supabase.co
//                   VITE_SUPABASE_ANON_KEY=<publishable/anon key from Dashboard -> Project Settings -> API>
//
// Usage:
//   const live = useLedgerRealtime();            // { enabled, status, settlement, chargebacks, loan, ... }
//   if (live.enabled) show live.loan.edi_status, live.chargebacks, live.events ...
//   after POST /reset on 8002/8003 call live.refetch()  (TRUNCATE is not streamed by Realtime)
//
// Never put the service-role key here: the anon key can only SELECT eight demo tables (RLS, mid-scoped).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createClient } from "@supabase/supabase-js";

const URL = import.meta.env.VITE_SUPABASE_URL;
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;
const DEFAULT_MID = import.meta.env.VITE_MID || "PAYTM_MERCH_8821";

let client = null;
function getClient() {
  if (!URL || !KEY) return null;
  if (!client) client = createClient(URL, KEY, { auth: { persistSession: false } });
  return client;
}

// table -> how to key rows and how many to keep
const TABLES = {
  "paytm.settlement_batches": { key: "batch_id", order: ["settlement_date", false], limit: 7 },
  "paytm.chargebacks":        { key: "case_id",  order: ["raised_at", false], limit: 20 },
  "paytm.loan_book":          { key: "loan_id",  order: ["loan_id", true], limit: 5 },
  "paytm.enach_mandates":     { key: "umrn",     order: ["umrn", true], limit: 5 },
  "paytm.utr_checks":         { key: "id",       order: ["id", false], limit: 50 },
  "paytm.verified_outcomes":  { key: "id",       order: ["id", false], limit: 50 },
  "paytm.agent_trace":        { key: "id",       order: ["id", false], limit: 200 },
  "merchant.a2a_events":      { key: "seq",      order: ["seq", false], limit: 200 },
};

function upsert(rows, row, key, limit, desc) {
  const next = rows.filter((r) => r[key] !== row[key]);
  next.push(row);
  next.sort((a, b) => (a[key] > b[key] ? 1 : -1) * (desc ? -1 : 1));
  return next.slice(0, limit);
}

export function useLedgerRealtime({ mid = DEFAULT_MID } = {}) {
  const sb = getClient();
  const [data, setData] = useState(() => Object.fromEntries(Object.keys(TABLES).map((t) => [t, []])));
  const [status, setStatus] = useState(sb ? "connecting" : "disabled");
  const [error, setError] = useState(null);
  const midRef = useRef(mid);
  midRef.current = mid;

  const refetch = useCallback(async () => {
    if (!sb) return;
    try {
      const entries = await Promise.all(
        Object.entries(TABLES).map(async ([full, cfg]) => {
          const [schema, table] = full.split(".");
          const { data: rows, error: err } = await sb
            .schema(schema).from(table).select("*").eq("mid", midRef.current)
            .order(cfg.order[0], { ascending: cfg.order[1] }).limit(cfg.limit);
          if (err) throw new Error(`${full}: ${err.message}`);
          return [full, rows || []];
        }),
      );
      setData(Object.fromEntries(entries));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [sb]);

  useEffect(() => {
    if (!sb) return undefined;
    refetch();
    let channel = sb.channel(`ledger-${mid}`);
    for (const [full, cfg] of Object.entries(TABLES)) {
      const [schema, table] = full.split(".");
      channel = channel.on(
        "postgres_changes",
        { event: "*", schema, table, filter: `mid=eq.${mid}` },
        (msg) => {
          setData((prev) => {
            const rows = prev[full] || [];
            const desc = !cfg.order[1];
            if (msg.eventType === "DELETE") {
              return { ...prev, [full]: rows.filter((r) => r[cfg.key] !== msg.old[cfg.key]) };
            }
            return { ...prev, [full]: upsert(rows, msg.new, cfg.key, cfg.limit, desc) };
          });
        },
      );
    }
    channel.subscribe((s) => {
      setStatus(s === "SUBSCRIBED" ? "live" : s.toLowerCase());
      if (s === "SUBSCRIBED") refetch(); // catch anything that changed while (re)connecting
    });
    return () => { sb.removeChannel(channel); };
  }, [sb, mid, refetch]);

  return useMemo(() => {
    const outcomes = data["paytm.verified_outcomes"];
    return {
      enabled: Boolean(sb),
      status,            // disabled | connecting | live | channel_error | timed_out | closed
      error,
      refetch,
      settlement: data["paytm.settlement_batches"][0] || null,
      chargebacks: data["paytm.chargebacks"],
      loan: data["paytm.loan_book"][0] || null,
      mandate: data["paytm.enach_mandates"][0] || null,
      utrChecks: data["paytm.utr_checks"],
      outcomes,
      trace: data["paytm.agent_trace"],
      events: [...data["merchant.a2a_events"]].reverse(), // oldest first, like GET /events
      counters: {
        outcomes_verified: outcomes.filter((o) => o.success).length,
        money_recovered_inr: outcomes.reduce((s, o) => s + Number(o.money_inr || 0), 0),
        fraud_blocked: data["paytm.utr_checks"].filter((u) => u.result === "NOT_FOUND_SUSPECTED_FAKE").length,
      },
    };
  }, [sb, status, error, refetch, data]);
}

export default useLedgerRealtime;
