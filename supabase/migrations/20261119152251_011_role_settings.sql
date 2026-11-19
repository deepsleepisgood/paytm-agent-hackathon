-- 011: session settings for the service roles live on the roles, not in the client connection string:
-- the Supabase pooler (transaction mode, :6543) does not forward startup `options`.
alter role paytm_svc set statement_timeout = '3s';
alter role merchant_svc set statement_timeout = '3s';
alter role paytm_svc set timezone = 'Asia/Kolkata';
alter role merchant_svc set timezone = 'Asia/Kolkata';
