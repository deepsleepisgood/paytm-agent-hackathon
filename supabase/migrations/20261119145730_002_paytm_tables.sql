-- 002: Paytm system of record (data/paytm). Columns mirror the dataset files.
-- `seeded` = row came from the dataset; reset_demo() deletes non-seeded rows.

create table paytm.merchant_master (
  mid text primary key, name text not null, category text, mcc text, city text, locality text, kyc_tier text,
  onboarded_on date, risk_tier text, avg_daily_gmv_6m bigint, settlement_cycle text, soundbox_count int,
  has_loan boolean, lender text, is_demo_merchant boolean not null default false);

create table paytm.acquiring_ledger (
  txn_id text primary key, mid text not null references paytm.merchant_master(mid), ts timestamptz not null,
  amount bigint not null check (amount > 0), method text not null, card_type text, network text, card_bin_masked text,
  payer_app text, utr text, rrn text, acquirer_ref text, npci_resp_code text, npci_resp_desc text,
  status paytm.txn_status not null, paytm_internal_status text, customer_id text, order_id text not null, channel text,
  settlement_batch_id text, mdr_rate_applied numeric(6,4), mdr_applied numeric(12,2), gst_applied numeric(12,2),
  risk_flag text, ingested_at timestamptz);
create index on paytm.acquiring_ledger (utr) where utr is not null;
create index on paytm.acquiring_ledger (order_id);
create index on paytm.acquiring_ledger (mid, ts);
create index on paytm.acquiring_ledger (settlement_batch_id);

create table paytm.npci_utr_log (
  utr text primary key check (utr ~ '^[0-9]{12}$'), txn_id text not null references paytm.acquiring_ledger(txn_id),
  payer_psp text, payer_vpa_masked text, payee_vpa text, amount bigint not null, status paytm.utr_status not null,
  merchant_view_status text, resp_code text, resp_desc text, initiated_at timestamptz, final_at timestamptz,
  reversal_due_by timestamptz, order_id text, duplicate_group_id text);
create index on paytm.npci_utr_log (txn_id);
create index on paytm.npci_utr_log (order_id);
create index on paytm.npci_utr_log (duplicate_group_id) where duplicate_group_id is not null;

create table paytm.settlement_batches (
  batch_id text primary key, mid text not null references paytm.merchant_master(mid), txn_date date not null,
  settlement_date date not null, txn_count int, gross bigint not null, mdr bigint not null, gst_on_mdr bigint not null,
  refunds bigint not null, soundbox_rental bigint not null, chargeback_hold bigint not null,
  chargeback_release bigint not null, net_credit bigint not null, variance bigint not null, payout_utr text,
  bank_account_masked text, ifsc text, status text, credited_at timestamptz, reconciled boolean,
  check (gross - mdr - gst_on_mdr - refunds - soundbox_rental - chargeback_hold + chargeback_release = net_credit));
create index on paytm.settlement_batches (mid, settlement_date);

create table paytm.settlement_lines (
  batch_id text not null references paytm.settlement_batches(batch_id), line_id text not null, line_type text not null,
  ref_id text, description text, amount_signed bigint not null, running_net bigint not null,
  primary key (batch_id, line_id));

create table paytm.mdr_rates (
  tier text not null, method text not null, rate_percent numeric(6,3) not null, primary key (tier, method));

create table paytm.policies (name text primary key, body jsonb not null);  -- genuinely flexible rule sets

create table paytm.shiprocket_pods (
  order_id text primary key, chargeback_id text, payment_txn_id text references paytm.acquiring_ledger(txn_id),
  awb text not null unique, courier text, ship_to text, amount bigint, shipped_at timestamptz,
  delivered_at timestamptz, recipient text, otp_verified boolean, signature boolean, photo_on_delivery boolean,
  document_path text, document_sha256 text, consent_id text, received_by_paytm_at timestamptz, items jsonb);

create table paytm.chargebacks (
  case_id text primary key, chargeback_id text not null unique, mid text not null references paytm.merchant_master(mid),
  txn_id text not null references paytm.acquiring_ledger(txn_id), order_id text not null, network text,
  reason_code text, reason_desc text, seed_reason_code text, amount bigint not null, hold_amount bigint not null,
  raised_at timestamptz not null, paytm_evidence_due timestamptz, network_response_due timestamptz,
  evidence_required text, evidence_received boolean not null default false, pod_awb text,
  status paytm.chargeback_status not null, outcome text, held_in_batch text, released_in_batch text,
  contract_ref text, updated_at timestamptz not null default now());
create index on paytm.chargebacks (txn_id);
create index on paytm.chargebacks (order_id);
create index on paytm.chargebacks (mid, status);

create table paytm.chargeback_status_history (
  id bigint generated always as identity primary key, case_id text not null references paytm.chargebacks(case_id),
  ts timestamptz not null, status text not null, actor text, note text, seeded boolean not null default false);
create index on paytm.chargeback_status_history (case_id);

create table paytm.refunds (
  refund_id text primary key, mid text not null references paytm.merchant_master(mid), order_id text not null,
  txn_id text not null references paytm.acquiring_ledger(txn_id), amount bigint not null check (amount > 0),
  type text not null, reason text, requested_at timestamptz, status paytm.refund_status not null,
  auto_eligible boolean, approver text, processed_at timestamptz, batch_id text,
  seeded boolean not null default false, updated_at timestamptz not null default now(),
  -- ₹5,000 autonomy limit enforced by the database too: a big refund needs a named human approver
  constraint refund_autonomy_limit check (
    status <> 'PROCESSED' or amount <= 5000 or (approver is not null and approver not like 'AUTO%')));
create index on paytm.refunds (txn_id);
create index on paytm.refunds (order_id);

create table paytm.loan_book (
  loan_id text primary key, mid text not null references paytm.merchant_master(mid), lender text not null,
  lender_role text, lsp text, product text, sanctioned_amount bigint, processing_fee bigint, net_disbursed bigint,
  disbursed_on date, apr_percent numeric(6,2), tenure_edis int, daily_edi bigint not null, total_repayable bigint,
  edis_due_so_far int, collected_so_far bigint not null, outstanding bigint not null, overdue_amount bigint not null,
  overdue_since date, dpd int not null, first_attempt_success_rate numeric(6,4), past_edi_success_rate text,
  kfs_edi_holiday_eligible boolean not null, edi_holiday_used_last_30_days boolean not null default false,
  kfs_clause_edi_holiday text, mandate_umrn text, status text,
  edi_status paytm.edi_status not null default 'ACTIVE', resume_date date, kfs_markdown text,
  updated_at timestamptz not null default now());

create table paytm.enach_mandates (
  umrn text primary key, mid text not null, loan_id text not null references paytm.loan_book(loan_id),
  sponsor_bank text, debtor_account_masked text, max_amount bigint, frequency text, registered_on date,
  valid_till date, status paytm.mandate_status not null, last_presentment date, last_result text, last_return text,
  updated_at timestamptz not null default now());

create table paytm.edi_collections (
  attempt_id text primary key, edi_date date not null, umrn text not null references paytm.enach_mandates(umrn),
  amount bigint not null, channel text not null, attempt_at timestamptz not null, result text not null,
  return_code text, return_reason text, collected_at timestamptz, dpd_after int,
  seeded boolean not null default false);
create index on paytm.edi_collections (umrn, edi_date);

create table paytm.upi_collect_links (
  link_id text primary key, loan_id text not null references paytm.loan_book(loan_id), edi_date date not null,
  amount bigint not null, created_at timestamptz not null default now(), valid_till timestamptz not null,
  status paytm.link_status not null default 'SENT', paid_at timestamptz);

create table paytm.lender_approvals (
  approval_id text primary key, loan_id text not null references paytm.loan_book(loan_id), type text not null,
  kfs_clause text not null, days int, approved_by text not null, consent_token text, ts timestamptz not null default now());

create table paytm.kfs_consent_artifacts (
  artifact_id text primary key, loan_id text not null references paytm.loan_book(loan_id), clause text not null,
  consent_token text not null, ts timestamptz not null default now());

create table paytm.risk_scores (
  date date not null, mid text not null references paytm.merchant_master(mid), health_score numeric(5,1),
  risk_tier text, gmv_7d_vs_90d numeric(6,2), edi_on_time_90d numeric(6,3), chargebacks_90d int,
  classification text, drivers text, primary key (mid, date));

create table paytm.fraud_signals (
  signal_id text primary key, ts timestamptz not null, mid text not null references paytm.merchant_master(mid),
  type text not null, ref text, detail text, score numeric(4,2), action text, outcome text, linked_ticket text,
  seeded boolean not null default false);
create index on paytm.fraud_signals (mid, ts);

create table paytm.soundbox_fleet (
  device_id text primary key, mid text not null references paytm.merchant_master(mid), model text, firmware text,
  imei_masked text, rental_inr_per_month bigint, billing_day int, installed_on date, status text,
  replacement_eligible boolean);

create table paytm.soundbox_telemetry (
  device_id text not null references paytm.soundbox_fleet(device_id), ts timestamptz not null, mid text not null,
  battery_pct int, battery_health_pct int, network text, signal_dbm int, heartbeat_ok boolean,
  announce_failures int, event text, firmware text, server_last_seen timestamptz, diagnosis text,
  primary key (device_id, ts));

create sequence paytm.ticket_seq start 1291;
create table paytm.tickets (
  ticket_id text primary key, mid text not null references paytm.merchant_master(mid), level paytm.ticket_level not null,
  intent text, summary text, channel text, opened_at timestamptz not null, assignee_team text, sla_due timestamptz,
  status paytm.ticket_status not null, outcome text, resolution text, resolved_at timestamptz, csat int,
  diagnostics jsonb, seeded boolean not null default false);
create index on paytm.tickets (mid, opened_at);

create table paytm.dpdp_consents (
  consent_id text primary key, mid text not null references paytm.merchant_master(mid), token text not null unique,
  purpose text, data_scope text, connector text, granted_at timestamptz not null, expires_at timestamptz not null,
  status paytm.consent_status not null, seeded boolean not null default false);

create table paytm.outcome_history (
  outcome_id text primary key, mid text not null references paytm.merchant_master(mid), date date, intent text,
  situation text, options text, option_chosen text, verified_outcome text, time_to_outcome text, success boolean,
  source text);
create index on paytm.outcome_history (intent, option_chosen);

create table paytm.scenarios (intent text primary key, body jsonb not null);
create table paytm.initial_state (id int primary key default 1 check (id = 1), body jsonb not null,
                                  loaded_at timestamptz not null default now());

-- ---------------------------------------------------------------- audit / event tables
create table paytm.consent_checks (
  id bigint generated always as identity primary key, ts timestamptz not null default now(), mid text,
  token text, purpose text, valid boolean not null, reason paytm.consent_reason not null, request_id text);
create table paytm.utr_checks (
  id bigint generated always as identity primary key, ts timestamptz not null default now(),
  mid text not null, utr text not null, result paytm.utr_check_result not null, txn_id text, request_id text);
create index on paytm.utr_checks (mid, ts);
create table paytm.agent_trace (
  id bigint generated always as identity primary key, ts timestamptz not null default now(), mid text not null,
  request_id text, intent text, seq int not null, agent text not null, reads text[], decision text,
  output jsonb, state_change jsonb);
create index on paytm.agent_trace (mid, ts);
create index on paytm.agent_trace (request_id);
create table paytm.verified_outcomes (
  id bigint generated always as identity primary key, ts timestamptz not null default now(), mid text not null,
  intent text not null, request_id text, option_chosen text, outcome text not null, success boolean not null,
  money_inr bigint not null default 0);
create index on paytm.verified_outcomes (mid, ts);
create table paytm.pending_credits (
  id bigint generated always as identity primary key, mid text not null, source_ref text not null,
  amount bigint not null, created_at timestamptz not null default now(), batch_hint text);
create table paytm.demo_counters (name text primary key, value bigint not null default 0);
insert into paytm.demo_counters (name) values ('outcomes_verified'), ('tickets_deflected'), ('fraud_blocked'),
  ('money_recovered_inr');
