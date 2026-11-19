-- 005: atomic Paytm business functions (called via RPC by paytm_svc).
-- Each function: validate -> lock rows -> change state -> audit row -> return new state.
-- Errors are raised as 'CODE: detail' so the service can map them (e.g. EDI_PAUSE_NOT_ELIGIBLE -> 409).

create sequence paytm.fraud_seq;
create sequence paytm.link_seq;
create sequence paytm.refund_seq;
create sequence paytm.approval_seq;
create sequence paytm.kfs_art_seq;
grant usage, select on all sequences in schema paytm to paytm_svc;

-- Snapshots of the mutable rows, taken right after loading; reset_demo() copies them back.
create table paytm.snap_refunds     (like paytm.refunds);
create table paytm.snap_chargebacks (like paytm.chargebacks);
create table paytm.snap_loan_book   (like paytm.loan_book);
create table paytm.snap_mandates    (like paytm.enach_mandates);
do $$ declare t text; begin
  foreach t in array array['snap_refunds', 'snap_chargebacks', 'snap_loan_book', 'snap_mandates'] loop
    execute format('alter table paytm.%I enable row level security', t);
    execute format('create policy svc_full_access on paytm.%I for all to paytm_svc using (true) with check (true)', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- consent (DPDP)
create or replace function paytm.check_consent(p_mid text, p_token text, p_purpose text default 'A2A dispatch',
                                               p_request_id text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare v_reason paytm.consent_reason; v_c paytm.dpdp_consents; v_id text; v_at timestamptz;
begin
  if p_token is null or btrim(p_token) = '' then
    v_reason := 'MISSING';
  elsif p_token !~ '^DPDP_VERIFIED_TS_[0-9]{10}$' then
    v_reason := 'MALFORMED';
  else
    select * into v_c from paytm.dpdp_consents where token = p_token;
    if found then
      v_id := v_c.consent_id;
      v_reason := case when v_c.status = 'REVOKED' then 'REVOKED'
                       when v_c.status = 'EXPIRED' or v_c.expires_at < now() then 'EXPIRED'
                       else 'OK' end::paytm.consent_reason;
    else
      -- tokens are minted by the merchant agent per request: valid for 24 h from their timestamp
      v_at := to_timestamp(substring(p_token from 18)::bigint);
      if v_at > now() + interval '5 minutes' then
        v_reason := 'MALFORMED';
      elsif v_at < now() - interval '24 hours' then
        v_reason := 'EXPIRED';
      else
        v_reason := 'OK';
        v_id := 'CNS-' || p_token;
        insert into paytm.dpdp_consents (consent_id, mid, token, purpose, data_scope, connector, granted_at, expires_at, status)
        values (v_id, p_mid, p_token, p_purpose, 'settlement, loan, disputes', 'MERCHANT_AGENT_8003', v_at,
                v_at + interval '24 hours', 'ACTIVE')
        on conflict (token) do nothing;
      end if;
    end if;
  end if;
  insert into paytm.consent_checks (mid, token, purpose, valid, reason, request_id)
  values (p_mid, p_token, p_purpose, v_reason = 'OK', v_reason, p_request_id);
  return jsonb_build_object('valid', v_reason = 'OK', 'reason', v_reason, 'consent_id', v_id,
                            'http_status', case when v_reason = 'OK' then 200 else 403 end);
end $$;

-- ---------------------------------------------------------------- UTR
create or replace function paytm.verify_utr(p_mid text, p_utr text, p_request_id text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare v paytm.npci_utr_log; v_result paytm.utr_check_result;
begin
  if p_utr is null or p_utr !~ '^[0-9]{12}$' then
    raise exception 'INVALID_UTR: % is not 12 digits', p_utr;
  end if;
  select * into v from paytm.npci_utr_log where utr = p_utr;
  if not found then
    v_result := 'NOT_FOUND_SUSPECTED_FAKE';
    insert into paytm.fraud_signals (signal_id, ts, mid, type, ref, detail, score, action, outcome)
    values ('FS-LIVE-' || lpad(nextval('paytm.fraud_seq')::text, 4, '0'), now(), p_mid, 'UTR_NOT_FOUND', p_utr,
            'UTR not in NPCI log (live lookup)', 0.95, 'Merchant warned: do not hand over goods', 'FRAUD_PREVENTED');
    update paytm.demo_counters set value = value + 1 where name = 'fraud_blocked';
  else
    v_result := v.status::text::paytm.utr_check_result;
  end if;
  insert into paytm.utr_checks (mid, utr, result, txn_id, request_id) values (p_mid, p_utr, v_result, v.txn_id, p_request_id);
  return jsonb_build_object('utr', p_utr, 'status', v_result, 'amount', v.amount, 'payer_app', v.payer_psp,
                            'txn_id', v.txn_id, 'order_id', v.order_id, 'settled', coalesce(v.status = 'SUCCESS', false),
                            'reversal_due_by', v.reversal_due_by);
end $$;

-- ---------------------------------------------------------------- chargeback
create or replace function paytm.release_chargeback(p_case_id text, p_pod_ref text default null,
                                                    p_request_id text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare c paytm.chargebacks; p paytm.shiprocket_pods;
begin
  select * into c from paytm.chargebacks
   where case_id = p_case_id or chargeback_id = p_case_id or order_id = p_case_id for update;
  if not found then raise exception 'CHARGEBACK_NOT_FOUND: %', p_case_id; end if;
  if c.status <> 'HELD' then raise exception 'CHARGEBACK_NOT_HELD: % is %', c.case_id, c.status; end if;
  select * into p from paytm.shiprocket_pods where order_id = c.order_id for update;
  if not found or p.delivered_at is null then raise exception 'POD_MISSING: order %', c.order_id; end if;
  if p_pod_ref is not null and p_pod_ref not in (p.awb, p.order_id, coalesce(p.document_path, '')) then
    raise exception 'POD_MISMATCH: % does not belong to order %', p_pod_ref, c.order_id;
  end if;
  if p.delivered_at > c.raised_at then raise exception 'POD_AFTER_DISPUTE: delivered after the dispute was raised'; end if;
  if not (coalesce(p.otp_verified, false) or coalesce(p.signature, false)) then
    raise exception 'POD_UNVERIFIED: no OTP or signature';
  end if;
  if c.paytm_evidence_due is not null and now() > c.paytm_evidence_due then
    raise exception 'EVIDENCE_DEADLINE_PASSED: due %', c.paytm_evidence_due;
  end if;
  update paytm.shiprocket_pods set received_by_paytm_at = coalesce(received_by_paytm_at, now()) where order_id = c.order_id;
  update paytm.chargebacks set status = 'RELEASED', evidence_received = true, outcome = 'RELEASED',
         released_in_batch = 'NEXT_T+1_BATCH', updated_at = now() where case_id = c.case_id;
  insert into paytm.chargeback_status_history (case_id, ts, status, actor, note) values
    (c.case_id, now(), 'EVIDENCE_SUBMITTED', 'ResolutionAgent', 'PoD AWB ' || p.awb),
    (c.case_id, now(), 'RELEASED', 'LedgerOpsAgent', 'Hold of ₹' || c.hold_amount || ' released');
  insert into paytm.pending_credits (mid, source_ref, amount, batch_hint) values (c.mid, c.case_id, c.hold_amount, 'next T+1 batch');
  update paytm.demo_counters set value = value + c.hold_amount where name = 'money_recovered_inr';
  return jsonb_build_object('case_id', c.case_id, 'chargeback_id', c.chargeback_id, 'order_id', c.order_id,
                            'txn_id', c.txn_id, 'status', 'RELEASED', 'released_amount', c.hold_amount,
                            'credit', 'next T+1 batch', 'pod_awb', p.awb);
end $$;

-- ---------------------------------------------------------------- EDI holiday (KFS 4.2, lender approval logged)
create or replace function paytm.pause_edi(p_loan_id text, p_days int, p_kfs_clause text, p_offer_id text default null,
                                           p_consent_token text default null, p_request_id text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare l paytm.loan_book; pol jsonb; v_reason text; v_c jsonb; v_appr text; v_art text;
        v_today date := (now() at time zone 'Asia/Kolkata')::date;
begin
  select * into l from paytm.loan_book where loan_id = p_loan_id for update;
  if not found then raise exception 'LOAN_NOT_FOUND: %', p_loan_id; end if;
  select body -> 'edi_holiday' into pol from paytm.policies where name = 'lender_policies';
  if p_consent_token is not null then
    v_c := paytm.check_consent(l.mid, p_consent_token, 'KFS 4.2 EDI holiday', p_request_id);
    if not (v_c ->> 'valid')::boolean then raise exception 'CONSENT_INVALID: %', v_c ->> 'reason'; end if;
  end if;
  v_reason := case
    when p_kfs_clause is distinct from coalesce(pol ->> 'kfs_clause', '4.2') then 'wrong KFS clause ' || coalesce(p_kfs_clause, 'null')
    when p_days is null or p_days < 1 or p_days > coalesce((pol ->> 'max_consecutive_days')::int, 2) then 'pause_days must be 1..2'
    when l.edi_status <> 'ACTIVE' then 'EDI is already ' || l.edi_status
    when not l.kfs_edi_holiday_eligible then 'loan is not eligible for an EDI holiday'
    when l.dpd > coalesce((pol ->> 'requires_dpd')::int, 0) then 'DPD above policy'
    when l.first_attempt_success_rate < coalesce((pol ->> 'min_first_attempt_success_90d')::numeric, 0.9) then 'EDI record below policy'
    when l.edi_holiday_used_last_30_days then 'EDI holiday already used in the last 30 days'
  end;
  if v_reason is not null then raise exception 'EDI_PAUSE_NOT_ELIGIBLE: %', v_reason; end if;
  v_appr := 'APPR-' || lpad(nextval('paytm.approval_seq')::text, 4, '0');
  v_art := 'KFS-ART-' || lpad(nextval('paytm.kfs_art_seq')::text, 4, '0');
  insert into paytm.lender_approvals (approval_id, loan_id, type, kfs_clause, days, approved_by, consent_token)
  values (v_appr, l.loan_id, 'EDI_HOLIDAY', p_kfs_clause, p_days,
          l.lender || ' credit ops (auto-approved: all clause 4.2 rules passed)', p_consent_token);
  insert into paytm.kfs_consent_artifacts (artifact_id, loan_id, clause, consent_token)
  values (v_art, l.loan_id, p_kfs_clause, coalesce(p_consent_token, 'NOT_PROVIDED'));
  update paytm.loan_book set edi_status = ('PAUSED_' || p_days || '_DAYS')::paytm.edi_status, resume_date = v_today + p_days,
         edi_holiday_used_last_30_days = true, updated_at = now() where loan_id = l.loan_id;
  return jsonb_build_object('status', 'EDI_PAUSED', 'loan_edi_status', 'PAUSED_' || p_days || '_DAYS', 'nbfc', l.lender,
    'pause_days', p_days, 'edi_saved_inr', l.daily_edi * p_days, 'edi_tomorrow', 0, 'resume_date', v_today + p_days,
    'offer_id', p_offer_id, 'lender_approval_id', v_appr,
    'kfs_consent_artifact', jsonb_build_object('artifact_id', v_art, 'clause', p_kfs_clause,
                                               'consent_token', p_consent_token, 'ts', extract(epoch from now())::bigint));
end $$;

-- ---------------------------------------------------------------- UPI fallback collection (KFS 4.1)
create or replace function paytm.send_upi_collect_link(p_loan_id text, p_edi_date date default null,
                                                       p_request_id text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare l paytm.loan_book; v_id text; v_date date; v_till timestamptz := now() + interval '24 hours';
begin
  select * into l from paytm.loan_book where loan_id = p_loan_id for update;
  if not found then raise exception 'LOAN_NOT_FOUND: %', p_loan_id; end if;
  if l.overdue_amount <= 0 then raise exception 'NOTHING_OVERDUE: loan %', p_loan_id; end if;
  v_date := coalesce(p_edi_date, l.overdue_since);
  v_id := 'UPIL-' || lpad(nextval('paytm.link_seq')::text, 4, '0');
  insert into paytm.upi_collect_links (link_id, loan_id, edi_date, amount, valid_till)
  values (v_id, l.loan_id, v_date, l.overdue_amount, v_till);
  update paytm.enach_mandates set status = 'UPI_LINK_SENT', updated_at = now() where loan_id = l.loan_id;
  return jsonb_build_object('link_id', v_id, 'edi_date', v_date, 'amount', l.overdue_amount, 'valid_till', v_till,
                            'mandate_status', 'UPI_LINK_SENT', 'bounce_charge', 0);
end $$;

create or replace function paytm.mark_upi_link_paid(p_link_id text)
returns jsonb language plpgsql set search_path = '' as $$
declare k paytm.upi_collect_links; v_umrn text; l paytm.loan_book;
begin
  select * into k from paytm.upi_collect_links where link_id = p_link_id for update;
  if not found then raise exception 'LINK_NOT_FOUND: %', p_link_id; end if;
  if k.status <> 'SENT' then raise exception 'LINK_NOT_OPEN: %', k.status; end if;
  select umrn into v_umrn from paytm.enach_mandates where loan_id = k.loan_id for update;
  update paytm.upi_collect_links set status = 'PAID', paid_at = now() where link_id = k.link_id;
  insert into paytm.edi_collections (attempt_id, edi_date, umrn, amount, channel, attempt_at, result, collected_at, dpd_after)
  values ('EDI-' || to_char(k.edi_date, 'YYMMDD') || '-' || k.link_id, k.edi_date, v_umrn, k.amount, 'UPI_LINK', now(),
          'SUCCESS', now(), 0);
  update paytm.loan_book set collected_so_far = collected_so_far + k.amount, outstanding = outstanding - k.amount,
         overdue_amount = greatest(0, overdue_amount - k.amount), dpd = 0,
         overdue_since = case when overdue_amount - k.amount <= 0 then null else overdue_since end, updated_at = now()
   where loan_id = k.loan_id returning * into l;
  update paytm.enach_mandates set status = 'ACTIVE', last_result = 'RECOVERED_VIA_UPI_LINK', updated_at = now()
   where umrn = v_umrn;
  update paytm.demo_counters set value = value + k.amount where name = 'money_recovered_inr';
  return jsonb_build_object('link_id', k.link_id, 'edi_date', k.edi_date, 'recovery', 'RECOVERED_VIA_UPI_LINK',
                            'overdue_amount', l.overdue_amount, 'outstanding', l.outstanding, 'dpd', l.dpd,
                            'mandate_status', 'ACTIVE', 'bounce_charge', 0);
end $$;

-- ---------------------------------------------------------------- refunds (₹5,000 autonomy limit, idempotent)
create or replace function paytm.execute_refund(p_txn_id text, p_amount bigint, p_reason text default null,
                                                p_approver text default null, p_refund_id text default null,
                                                p_request_id text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare t paytm.acquiring_ledger; r paytm.refunds; v_done bigint; v_status paytm.refund_status; v_human boolean;
begin
  if p_amount is null or p_amount <= 0 then raise exception 'INVALID_AMOUNT: %', p_amount; end if;
  select * into t from paytm.acquiring_ledger where txn_id = p_txn_id;
  if not found then raise exception 'TXN_NOT_FOUND: %', p_txn_id; end if;
  if t.status <> 'SUCCESS' then raise exception 'TXN_NOT_SETTLED: % is %', p_txn_id, t.status; end if;
  select * into r from paytm.refunds
   where refund_id = p_refund_id
      or (p_refund_id is null and txn_id = p_txn_id and status in ('CANDIDATE', 'QUEUED', 'NEEDS_APPROVAL'))
   order by (refund_id = coalesce(p_refund_id, '')) desc limit 1 for update;
  if found and r.status = 'PROCESSED' then
    return jsonb_build_object('refund_id', r.refund_id, 'status', r.status, 'amount', r.amount, 'txn_id', r.txn_id,
                              'order_id', r.order_id, 'approver', r.approver, 'idempotent_replay', true);
  end if;
  select coalesce(sum(amount), 0) into v_done from paytm.refunds where txn_id = p_txn_id and status = 'PROCESSED';
  if v_done + p_amount > t.amount then
    raise exception 'REFUND_EXCEEDS_PAYMENT: ₹% already refunded of ₹%', v_done, t.amount;
  end if;
  v_human := p_approver is not null and p_approver not like 'AUTO%';
  v_status := case when p_amount <= 5000 or v_human then 'PROCESSED' else 'NEEDS_APPROVAL' end;
  if r.refund_id is not null then
    update paytm.refunds set amount = p_amount, status = v_status, reason = coalesce(p_reason, reason),
           approver = case when v_status = 'PROCESSED' then coalesce(p_approver, 'AUTO (≤ ₹5,000)') end,
           processed_at = case when v_status = 'PROCESSED' then now() end, updated_at = now()
     where refund_id = r.refund_id returning * into r;
  else
    insert into paytm.refunds (refund_id, mid, order_id, txn_id, amount, type, reason, requested_at, status,
                               auto_eligible, approver, processed_at)
    values (coalesce(p_refund_id, 'RFD-LIVE-' || lpad(nextval('paytm.refund_seq')::text, 4, '0')), t.mid, t.order_id,
            t.txn_id, p_amount, 'AGENT', p_reason, now(), v_status, p_amount <= 5000,
            case when v_status = 'PROCESSED' then coalesce(p_approver, 'AUTO (≤ ₹5,000)') end,
            case when v_status = 'PROCESSED' then now() end)
    returning * into r;
  end if;
  return jsonb_build_object('refund_id', r.refund_id, 'status', r.status, 'amount', r.amount, 'txn_id', r.txn_id,
                            'order_id', r.order_id, 'approver', r.approver,
                            'needs_human_approval', r.status = 'NEEDS_APPROVAL');
end $$;

-- ---------------------------------------------------------------- tickets, outcomes, traces
create or replace function paytm.create_l2_ticket(p_mid text, p_intent text, p_summary text,
                                                  p_diagnostics jsonb default '{}'::jsonb)
returns jsonb language plpgsql set search_path = '' as $$
declare v_id text := 'TKT-PAYTM-' || nextval('paytm.ticket_seq'); v_sla timestamptz := now() + interval '24 hours';
        v_team text := case when p_intent = 'ESCALATE_HUMAN' then 'Device Ops' else 'Merchant Support L2' end;
begin
  insert into paytm.tickets (ticket_id, mid, level, intent, summary, channel, opened_at, assignee_team, sla_due, status, diagnostics)
  values (v_id, p_mid, 'L2', p_intent, p_summary, 'a2a', now(), v_team, v_sla, 'OPEN', p_diagnostics);
  return jsonb_build_object('ticket_id', v_id, 'level', 'L2', 'assignee_team', v_team, 'sla_due', v_sla, 'status', 'OPEN');
end $$;

create or replace function paytm.record_outcome(p_mid text, p_intent text, p_request_id text, p_option_chosen text,
                                                p_outcome text, p_success boolean, p_money_inr bigint default 0)
returns jsonb language plpgsql set search_path = '' as $$
declare v_id bigint;
begin
  insert into paytm.verified_outcomes (mid, intent, request_id, option_chosen, outcome, success, money_inr)
  values (p_mid, p_intent, p_request_id, p_option_chosen, p_outcome, p_success, coalesce(p_money_inr, 0))
  returning id into v_id;
  if p_success then
    update paytm.demo_counters set value = value + 1 where name = 'outcomes_verified';
    if p_intent <> 'ESCALATE_HUMAN' then
      update paytm.demo_counters set value = value + 1 where name = 'tickets_deflected';
    end if;
  end if;
  return jsonb_build_object('outcome_id', v_id,
                            'counters', (select jsonb_object_agg(name, value) from paytm.demo_counters));
end $$;

create or replace function paytm.log_agent_trace(p_mid text, p_request_id text, p_intent text, p_steps jsonb)
returns int language plpgsql set search_path = '' as $$
declare n int;
begin
  insert into paytm.agent_trace (mid, request_id, intent, seq, agent, reads, decision, output, state_change)
  select p_mid, p_request_id, p_intent, s.ord::int, coalesce(s.step ->> 'agent', 'unknown'),
         array(select jsonb_array_elements_text(coalesce(s.step -> 'reads', '[]'::jsonb))),
         coalesce(s.step ->> 'decision', s.step ->> 'note', s.step ->> 'output'), s.step, s.step -> 'state_change'
    from jsonb_array_elements(coalesce(p_steps, '[]'::jsonb)) with ordinality as s(step, ord);
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------- snapshot + reset (one transaction)
create or replace function paytm.take_snapshot()
returns jsonb language plpgsql set search_path = '' as $$
begin
  truncate paytm.snap_refunds, paytm.snap_chargebacks, paytm.snap_loan_book, paytm.snap_mandates;
  insert into paytm.snap_refunds select * from paytm.refunds where seeded;
  insert into paytm.snap_chargebacks select * from paytm.chargebacks;
  insert into paytm.snap_loan_book select * from paytm.loan_book;
  insert into paytm.snap_mandates select * from paytm.enach_mandates;
  return jsonb_build_object('refunds', (select count(*) from paytm.snap_refunds),
                            'chargebacks', (select count(*) from paytm.snap_chargebacks));
end $$;

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
  update paytm.chargebacks c set status = n.status, evidence_received = n.evidence_received, outcome = n.outcome,
         released_in_batch = n.released_in_batch, paytm_evidence_due = n.paytm_evidence_due, updated_at = now()
    from paytm.snap_chargebacks n where n.case_id = c.case_id;
  update paytm.loan_book l set edi_status = n.edi_status, resume_date = n.resume_date, collected_so_far = n.collected_so_far,
         outstanding = n.outstanding, overdue_amount = n.overdue_amount, overdue_since = n.overdue_since, dpd = n.dpd,
         edi_holiday_used_last_30_days = n.edi_holiday_used_last_30_days, updated_at = now()
    from paytm.snap_loan_book n where n.loan_id = l.loan_id;
  update paytm.enach_mandates m set status = n.status, last_result = n.last_result, last_return = n.last_return,
         updated_at = now()
    from paytm.snap_mandates n where n.umrn = m.umrn;
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

-- only the Paytm service role may execute these
revoke execute on all functions in schema paytm from public;
grant execute on all functions in schema paytm to paytm_svc;
