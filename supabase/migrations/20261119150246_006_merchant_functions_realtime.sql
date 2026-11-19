-- 006: merchant-side functions (called by merchant_svc) + Realtime publication.

create or replace function merchant.log_event(p_type text, p_actor text, p_summary text, p_payload jsonb default '{}'::jsonb,
                                              p_request_id text default null, p_session_id text default null,
                                              p_mid text default 'PAYTM_MERCH_8821')
returns bigint language plpgsql set search_path = '' as $$
declare v_seq bigint;
begin
  insert into merchant.a2a_events (mid, session_id, type, actor, request_id, summary, payload)
  values (p_mid, p_session_id, p_type, p_actor, p_request_id, p_summary, coalesce(p_payload, '{}'::jsonb))
  returning seq into v_seq;
  return v_seq;
end $$;

-- idempotent: the same (settlement_date, amount) is only logged once
create or replace function merchant.add_gst_itc(p_settlement_date date, p_amount bigint, p_basis text,
                                                p_source_request_id text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare v merchant.gst_itc_log;
begin
  insert into merchant.gst_itc_log (settlement_date, amount, basis, source_request_id)
  values (p_settlement_date, p_amount, p_basis, p_source_request_id)
  on conflict (settlement_date, amount) do nothing returning * into v;
  return jsonb_build_object('logged', v.id is not null,
                            'itc_total', (select coalesce(sum(amount), 0) from merchant.gst_itc_log));
end $$;

create or replace function merchant.record_strategy(p_intent text, p_situation text, p_options text[], p_chosen text,
                                                    p_verified_outcome text, p_success boolean,
                                                    p_time_to_outcome text default null)
returns text language plpgsql set search_path = '' as $$
declare v_id text := 'SM-LIVE-' || to_char(clock_timestamp(), 'HH24MISSMS');
begin
  insert into merchant.strategy_memory (memory_id, date, intent, situation, options_considered, chosen,
                                        verified_outcome, time_to_outcome, success)
  values (v_id, (now() at time zone 'Asia/Kolkata')::date, p_intent, p_situation, p_options, p_chosen,
          p_verified_outcome, p_time_to_outcome, p_success);
  return v_id;
end $$;

create or replace function merchant.reset_demo()
returns jsonb language plpgsql set search_path = '' as $$
declare t0 timestamptz := clock_timestamp();
begin
  truncate merchant.a2a_events, merchant.gst_itc_log, merchant.fraud_alerts, merchant.dispute_packets,
           merchant.edi_offers restart identity;
  delete from merchant.strategy_memory where not seeded;
  delete from merchant.khata where not seeded;
  update merchant.agent_state set value = 'ACTIVE' where key = 'loan_edi_status';
  return jsonb_build_object('restored', true, 'ms', round(extract(epoch from clock_timestamp() - t0) * 1000, 1));
end $$;

revoke execute on all functions in schema merchant from public;
grant execute on all functions in schema merchant to merchant_svc;

-- ---------------------------------------------------------------- Realtime (ledger column + trace column)
alter publication supabase_realtime add table
  paytm.settlement_batches, paytm.chargebacks, paytm.loan_book, paytm.enach_mandates,
  paytm.utr_checks, paytm.verified_outcomes, paytm.agent_trace, merchant.a2a_events;
