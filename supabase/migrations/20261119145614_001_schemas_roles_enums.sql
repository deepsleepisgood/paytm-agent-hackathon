-- 001: schemas, service roles, enums.
-- Two schemas keep the merchant <-> Paytm boundary: each service gets a Postgres login
-- role that can only use its own schema. They talk to each other only over A2A HTTP.

create schema if not exists merchant;
create schema if not exists paytm;

-- Service roles (passwords are set by hand in the SQL editor, never committed):
--   alter role paytm_svc    with password '...';
--   alter role merchant_svc with password '...';
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'paytm_svc') then
    create role paytm_svc login noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'merchant_svc') then
    create role merchant_svc login noinherit;
  end if;
end $$;

-- ---------------------------------------------------------------- enums (contract.md values)
create type paytm.txn_status       as enum ('SUCCESS', 'PENDING', 'FAILED');
create type paytm.utr_status       as enum ('SUCCESS', 'PENDING', 'FAILED', 'REVERSED');
create type paytm.utr_check_result as enum ('SUCCESS', 'PENDING', 'FAILED', 'REVERSED', 'NOT_FOUND_SUSPECTED_FAKE');
create type paytm.chargeback_status as enum ('HELD', 'RELEASED', 'WON', 'LOST');
create type paytm.refund_status    as enum ('CANDIDATE', 'QUEUED', 'NEEDS_APPROVAL', 'PROCESSED', 'REJECTED');
-- contract.md V2: loan_edi_status ACTIVE -> PAUSED_2_DAYS (f"PAUSED_{days}_DAYS")
create type paytm.edi_status       as enum ('ACTIVE', 'PAUSED_1_DAYS', 'PAUSED_2_DAYS');
create type paytm.mandate_status   as enum ('ACTIVE', 'BOUNCED', 'UPI_LINK_SENT');
create type paytm.consent_status   as enum ('ACTIVE', 'EXPIRED', 'REVOKED');
create type paytm.consent_reason   as enum ('OK', 'MISSING', 'MALFORMED', 'EXPIRED', 'REVOKED');
create type paytm.ticket_level     as enum ('L1', 'L2');
create type paytm.ticket_status    as enum ('OPEN', 'CLOSED');
create type paytm.link_status      as enum ('SENT', 'PAID', 'EXPIRED');

create type merchant.txn_status       as enum ('SUCCESS', 'PENDING', 'FAILED');
create type merchant.chargeback_status as enum ('HELD', 'RELEASED', 'WON', 'LOST');
create type merchant.payable_status   as enum ('PAID', 'DUE');
