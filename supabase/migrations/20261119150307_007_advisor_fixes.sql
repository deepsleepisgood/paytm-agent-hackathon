-- 007: fixes from Supabase's performance advisor (unindexed foreign keys, snapshot tables without PKs).
-- "unused_index" notices are expected on a freshly created database and are left as they are.
create index on merchant.chargebacks (txn_id);
create index on merchant.refunds (txn_id);
create index on merchant.shipments (customer_id);
create index on merchant.shipments (payment_txn_id);
create index on merchant.utr_ledger (txn_id);
create index on paytm.dpdp_consents (mid);
create index on paytm.enach_mandates (loan_id);
create index on paytm.kfs_consent_artifacts (loan_id);
create index on paytm.lender_approvals (loan_id);
create index on paytm.loan_book (mid);
create index on paytm.outcome_history (mid);
create index on paytm.refunds (mid);
create index on paytm.shiprocket_pods (payment_txn_id);
create index on paytm.soundbox_fleet (mid);
create index on paytm.upi_collect_links (loan_id);
alter table paytm.snap_refunds     add primary key (refund_id);
alter table paytm.snap_chargebacks add primary key (case_id);
alter table paytm.snap_loan_book   add primary key (loan_id);
alter table paytm.snap_mandates    add primary key (umrn);
