-- 010: found by running the services' tests as paytm_svc / merchant_svc (not the owner).
-- reset_demo truncates audit tables and calls setval(), which need TRUNCATE / sequence UPDATE.
-- Rather than granting those to the service roles for every table, the two reset functions run
-- with the owner's rights (search_path is pinned, execute is granted only to the owning service role).
-- take_snapshot defines the reset baseline: only the loader (owner) may call it.

alter function paytm.reset_demo(numeric) security definer;
alter function paytm._restore_from_snapshot(text, text, text) security definer;
alter function merchant.reset_demo() security definer;

revoke execute on function paytm._restore_from_snapshot(text, text, text) from paytm_svc;
revoke execute on function paytm.take_snapshot() from paytm_svc;
revoke execute on function paytm.reset_demo(numeric) from public, anon, authenticated;
revoke execute on function merchant.reset_demo() from public, anon, authenticated;
grant execute on function paytm.reset_demo(numeric) to paytm_svc;
grant execute on function merchant.reset_demo() to merchant_svc;
