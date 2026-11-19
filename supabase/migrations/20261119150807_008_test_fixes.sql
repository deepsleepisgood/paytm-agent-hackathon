-- 008: fixes found while testing the functions via SQL.
-- 1) merchant.log_event: an explicit NULL p_mid bypassed the column default -> default it in the function.
-- 2) Let the dashboard/MCP owner role assume the service roles (SET only, no inherit) so the
--    schema boundary can be tested with `set local role paytm_svc` / `merchant_svc`.

create or replace function merchant.log_event(
  p_type text, p_actor text, p_summary text, p_payload jsonb default '{}'::jsonb,
  p_request_id text default null, p_session_id text default null, p_mid text default 'PAYTM_MERCH_8821')
returns bigint language plpgsql security invoker set search_path = '' as $$
declare v_seq bigint;
begin
  insert into merchant.a2a_events (mid, session_id, type, actor, request_id, summary, payload)
  values (coalesce(p_mid, 'PAYTM_MERCH_8821'), p_session_id, p_type, p_actor, p_request_id, p_summary,
          coalesce(p_payload, '{}'::jsonb))
  returning seq into v_seq;
  return v_seq;
end $$;
revoke execute on function merchant.log_event(text, text, text, jsonb, text, text, text) from public, anon, authenticated;
grant execute on function merchant.log_event(text, text, text, jsonb, text, text, text) to merchant_svc;

grant paytm_svc to postgres with inherit false, set true;
grant merchant_svc to postgres with inherit false, set true;
