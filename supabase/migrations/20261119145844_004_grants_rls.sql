-- 004: grants + row-level security (deny by default).
--  * paytm_svc    -> schema paytm only      (Paytm agent, :8002)
--  * merchant_svc -> schema merchant only   (merchant agent, :8003)
--  * anon         -> SELECT on the 8 live ledger tables, PAYTM_MERCH_8821 rows only (frontend + Realtime)
-- The service-role key bypasses RLS and both schemas, so services never use it; only the loader does.

revoke all on schema paytm, merchant from public;

grant usage on schema paytm to paytm_svc;
grant select, insert, update, delete on all tables in schema paytm to paytm_svc;
grant usage, select on all sequences in schema paytm to paytm_svc;
alter default privileges in schema paytm grant select, insert, update, delete on tables to paytm_svc;
alter default privileges in schema paytm grant usage, select on sequences to paytm_svc;

grant usage on schema merchant to merchant_svc;
grant select, insert, update, delete on all tables in schema merchant to merchant_svc;
grant usage, select on all sequences in schema merchant to merchant_svc;
alter default privileges in schema merchant grant select, insert, update, delete on tables to merchant_svc;
alter default privileges in schema merchant grant usage, select on sequences to merchant_svc;

-- RLS on every table + a full-access policy for the owning service role only
do $$
declare r record;
begin
  for r in select schemaname, tablename from pg_tables where schemaname in ('paytm', 'merchant') loop
    execute format('alter table %I.%I enable row level security', r.schemaname, r.tablename);
    execute format('create policy svc_full_access on %I.%I for all to %I using (true) with check (true)',
                   r.schemaname, r.tablename, case r.schemaname when 'paytm' then 'paytm_svc' else 'merchant_svc' end);
  end loop;
end $$;

-- Frontend (anon): read-only, demo merchant only
grant usage on schema paytm, merchant to anon;
grant select on paytm.settlement_batches, paytm.chargebacks, paytm.loan_book, paytm.enach_mandates,
               paytm.utr_checks, paytm.verified_outcomes, paytm.agent_trace, merchant.a2a_events to anon;
create policy anon_read_demo on paytm.settlement_batches for select to anon using (mid = 'PAYTM_MERCH_8821');
create policy anon_read_demo on paytm.chargebacks       for select to anon using (mid = 'PAYTM_MERCH_8821');
create policy anon_read_demo on paytm.loan_book         for select to anon using (mid = 'PAYTM_MERCH_8821');
create policy anon_read_demo on paytm.enach_mandates    for select to anon using (mid = 'PAYTM_MERCH_8821');
create policy anon_read_demo on paytm.utr_checks        for select to anon using (mid = 'PAYTM_MERCH_8821');
create policy anon_read_demo on paytm.verified_outcomes for select to anon using (mid = 'PAYTM_MERCH_8821');
create policy anon_read_demo on paytm.agent_trace       for select to anon using (mid = 'PAYTM_MERCH_8821');
create policy anon_read_demo on merchant.a2a_events     for select to anon using (mid = 'PAYTM_MERCH_8821');
