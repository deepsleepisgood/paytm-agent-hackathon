-- 009: reset_demo restored only a hand-picked column list and stamped updated_at = now(), so a reset was not
-- byte-identical to the snapshot (found by supabase/tests/test_supabase_db.py). Restore every column instead.

create or replace function paytm._restore_from_snapshot(p_table text, p_snap text, p_key text)
returns void language plpgsql set search_path = '' as $$
declare v_cols text;
begin
  select string_agg(format('%I', column_name), ', ' order by ordinal_position) into v_cols
    from information_schema.columns
   where table_schema = 'paytm' and table_name = p_table and column_name <> p_key and is_generated = 'NEVER';
  execute format('update paytm.%I t set (%s) = (select %s from paytm.%I n where n.%I = t.%I)',
                 p_table, v_cols, v_cols, p_snap, p_key, p_key);
end $$;
revoke execute on function paytm._restore_from_snapshot(text, text, text) from public, anon, authenticated;
grant execute on function paytm._restore_from_snapshot(text, text, text) to paytm_svc;

create or replace function paytm.reset_demo(p_chargeback_hours_left numeric default 48)
returns jsonb language plpgsql set search_path = '' as $$
declare s jsonb; t0 timestamptz := clock_timestamp();
begin
  select body into s from paytm.initial_state where id = 1;
  if s is null then raise exception 'INITIAL_STATE_MISSING: run supabase/seed/load_seed.py first'; end if;
  truncate paytm.consent_checks, paytm.utr_checks, paytm.agent_trace, paytm.verified_outcomes, paytm.pending_credits,
           paytm.upi_collect_links, paytm.lender_approvals, paytm.kfs_consent_artifacts;
  delete from paytm.chargeback_status_history where not seeded;
  delete from paytm.edi_collections where not seeded;
  delete from paytm.tickets where not seeded;
  delete from paytm.fraud_signals where not seeded;
  delete from paytm.dpdp_consents where not seeded;
  delete from paytm.refunds;
  insert into paytm.refunds select * from paytm.snap_refunds;
  -- restore every column (incl. updated_at) of the mutable rows from their snapshots
  perform paytm._restore_from_snapshot('chargebacks', 'snap_chargebacks', 'case_id');
  perform paytm._restore_from_snapshot('loan_book', 'snap_loan_book', 'loan_id');
  perform paytm._restore_from_snapshot('enach_mandates', 'snap_mandates', 'umrn');
  update paytm.shiprocket_pods set received_by_paytm_at = null;
  update paytm.demo_counters set value = 0;
  -- keep the 48 h evidence window live relative to "now", as the in-memory service does
  if p_chargeback_hours_left is not null then
    update paytm.chargebacks set paytm_evidence_due = now() + make_interval(secs => p_chargeback_hours_left * 3600)
     where status = 'HELD';
  end if;
  perform setval('paytm.ticket_seq', substring(s ->> 'next_ticket_id' from '[0-9]+$')::bigint, false);
  perform setval('paytm.fraud_seq', 1, false);
  perform setval('paytm.link_seq', 1, false);
  perform setval('paytm.refund_seq', 1, false);
  perform setval('paytm.approval_seq', 1, false);
  perform setval('paytm.kfs_art_seq', 1, false);
  return jsonb_build_object('restored', true, 'ms', round(extract(epoch from clock_timestamp() - t0) * 1000, 1),
    'chargeback_9981', (select status from paytm.chargebacks where chargeback_id = 'CB-9981'),
    'loan_edi_status', (select edi_status from paytm.loan_book limit 1),
    'refunds', (select jsonb_object_agg(refund_id, status) from paytm.refunds
                 where refund_id in ('RFD-4412', 'RFD-4490') or refund_id like 'RFD-DUP-%'));
end $$;
revoke execute on function paytm.reset_demo(numeric) from public, anon, authenticated;
grant execute on function paytm.reset_demo(numeric) to paytm_svc;
