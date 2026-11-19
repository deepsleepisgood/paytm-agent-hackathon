-- 003: Merchant-side data (data/seed) + the merchant agent's own state.
-- Only merchant_svc (and anon for a2a_events) may touch this schema.

create table merchant.profile (
  mid text primary key, name text not null, owner text, category text, mcc text, kyc_tier text, gstin text,
  address_line1 text, city text, state text, pincode text, store_hours text, onboarded_on date,
  settlement_cycle text, bank_masked text, ifsc text,
  -- historical_memory: fixed 8-key shape from contract.md, so typed columns
  daily_avg_sales bigint not null, weekend_multiplier text not null, past_edi_success_rate text not null,
  tomorrow_stock_payable bigint not null, active_lender text not null, daily_edi bigint not null,
  loan_balance bigint not null, kfs_edi_holiday_eligible boolean not null, as_of timestamptz);

create table merchant.connectors (
  mid text not null references merchant.profile(mid), name text not null, status text not null,
  dpdp_consent text not null, granted_at date, holds text, primary key (mid, name));

create table merchant.customers (
  customer_id text primary key, name text not null, phone_masked text, locality text, segment text,
  first_seen date, on_khata boolean, preferred_app text);

create table merchant.transactions (
  txn_id text primary key, ts timestamptz not null, amount bigint not null check (amount > 0), method text not null,
  card_type text, payer_app text, utr text, status merchant.txn_status not null,
  customer_id text not null references merchant.customers(customer_id), order_id text not null, channel text,
  mdr_rate numeric(6,4), mdr_amount numeric(12,2), settlement_batch_id text, tag text);
create index on merchant.transactions (utr) where utr is not null;
create index on merchant.transactions (order_id);
create index on merchant.transactions (ts);
create index on merchant.transactions (customer_id);

create table merchant.daily_sales (
  date date primary key, weekday text, gross bigint not null, txn_count int, avg_ticket numeric(10,1),
  upi_share_by_value numeric(5,3), is_weekend boolean, is_festival boolean, rain_dip boolean, closure_dip boolean,
  bulk_order_day boolean, note text);

create table merchant.settlements (
  batch_id text primary key, settlement_date date not null, txn_date date not null, gross bigint not null,
  mdr bigint not null, gst_on_mdr bigint not null, refunds bigint not null, soundbox_rental bigint not null,
  chargeback_hold bigint not null, chargeback_release bigint not null, net_credit bigint not null,
  variance bigint not null, credited_at timestamptz, payout_ref text, status text);
create index on merchant.settlements (settlement_date);

create table merchant.settlement_deductions (
  batch_id text not null references merchant.settlements(batch_id), type text not null, amount bigint not null,
  source text, txn_id text, primary key (batch_id, type));

create table merchant.loan (
  loan_id text primary key, lender text not null, daily_edi bigint not null, sanctioned_amount bigint,
  total_repayable bigint, collected_so_far bigint, loan_balance bigint not null, apr_percent numeric(6,2),
  collection_method text, mandate_umrn text, kfs_edi_holiday_eligible boolean not null,
  kfs_clauses jsonb);  -- free-text clauses: flexible

create table merchant.edi_schedule (
  edi_date date primary key, amount bigint not null, channel text, status text not null, bounce_code text,
  bounce_reason text, context text, recovery text, recovery_note text, cumulative_collected bigint,
  balance_after bigint);

create table merchant.refunds (
  refund_id text primary key, order_id text not null, txn_id text not null references merchant.transactions(txn_id),
  customer_id text, amount bigint not null, reason text, requested_at timestamptz, processed_at timestamptz,
  status text not null, deducted_in_batch text);

create table merchant.chargebacks (
  chargeback_id text primary key, txn_id text not null references merchant.transactions(txn_id),
  order_id text not null, customer_id text, amount bigint not null, reason_code text, raised_at timestamptz,
  respond_by timestamptz, status merchant.chargeback_status not null, resolved_at timestamptz,
  held_in_batch text, released_in_batch text, pod_awb text, evidence text, contract_ref text);

create table merchant.shipments (
  order_id text primary key, ondc_order_id text, buyer_app text, customer_id text references merchant.customers(customer_id),
  ship_to text, amount bigint not null, payment_txn_id text references merchant.transactions(txn_id),
  ordered_at timestamptz, courier text, awb text unique, shipped_at timestamptz, status text not null);
create table merchant.shipment_items (
  order_id text not null references merchant.shipments(order_id), sku text not null, name text, qty int not null,
  price bigint not null, primary key (order_id, sku));
create table merchant.pods (
  order_id text primary key references merchant.shipments(order_id), delivered_at timestamptz, recipient text,
  otp_verified boolean, signature boolean, photo_on_delivery boolean, document text);

create table merchant.utr_ledger (
  utr text primary key, txn_id text not null references merchant.transactions(txn_id), amount bigint not null,
  payer_app text, payer_vpa_masked text, npci_status text, ts timestamptz, order_id text, customer_id text, flag text);
create index on merchant.utr_ledger (order_id);

create table merchant.supplier_payables (
  payable_id text primary key, supplier text not null, invoice_no text, amount bigint not null, invoice_date date,
  due_date date, status merchant.payable_status not null, paid_on date, source text);
create index on merchant.supplier_payables (due_date);

create table merchant.khata (
  entry_id text primary key, customer_id text not null references merchant.customers(customer_id),
  ts timestamptz not null, type text not null, amount bigint not null, txn_id text, balance_after bigint, note text,
  seeded boolean not null default false);
create index on merchant.khata (customer_id, ts);

create table merchant.inventory (
  sku text primary key, name text not null, brand text, category text, unit text, cost_price bigint,
  selling_price bigint, mrp bigint, margin_pct numeric(5,1), stock_qty int, reorder_point int,
  below_reorder boolean, supplier text, weekend_stockout_count_6m int);

create table merchant.device_logs (
  ts timestamptz not null, device_id text not null, device text, battery_pct int, battery_health_pct int,
  network text, signal_dbm int, heartbeat_ok boolean, announce_failures int, event text,
  primary key (device_id, ts));

create table merchant.support_history (
  ticket_id text primary key, opened_at timestamptz, intent text, summary text, channel text, resolution text,
  resolved_at timestamptz, outcome text, csat int);

create table merchant.strategy_memory (
  memory_id text primary key, date date, intent text, situation text, options_considered text[], chosen text,
  verified_outcome text, time_to_outcome text, success boolean, seeded boolean not null default false,
  created_at timestamptz not null default now());

create table merchant.scenarios (intent text primary key, body jsonb not null);

-- ---------------------------------------------------------------- merchant agent state
create table merchant.a2a_events (
  seq bigint generated always as identity primary key, ts timestamptz not null default now(),
  mid text not null default 'PAYTM_MERCH_8821', session_id text, type text not null, actor text not null,
  request_id text, summary text, payload jsonb not null default '{}'::jsonb);  -- payload shape varies by event
create index on merchant.a2a_events (mid, ts);
create table merchant.gst_itc_log (
  id bigint generated always as identity primary key, settlement_date date not null, amount bigint not null,
  basis text, source_request_id text, logged_at timestamptz not null default now(),
  unique (settlement_date, amount));
create table merchant.fraud_alerts (
  id bigint generated always as identity primary key, ts timestamptz not null default now(), utr text, payload jsonb);
create table merchant.dispute_packets (
  packet_id text primary key, status text not null, body jsonb not null, updated_at timestamptz not null default now());
create table merchant.edi_offers (
  offer_id text primary key, status text not null, body jsonb not null, updated_at timestamptz not null default now());
create table merchant.agent_state (key text primary key, value text not null);  -- e.g. loan_edi_status
insert into merchant.agent_state values ('loan_edi_status', 'ACTIVE');
