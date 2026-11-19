#!/usr/bin/env python3
"""One-shot local setup for Supabase mode. Run from the repo root on your laptop:

    python supabase/seed/setup_local.py

1. Asks for the Supabase *database* password (hidden prompt; it is only written to supabase/.env, git-ignored).
2. Finds the right Session-pooler host and saves SUPABASE_DB_URL in supabase/.env.
3. Loads data/seed + data/paytm (load_seed.py) and verifies against ledger_initial_state.json.
4. Gives paytm_svc / merchant_svc fresh random passwords (sent as SCRAM hashes, so the plain text never
   reaches Postgres logs) and writes USE_SUPABASE=true + PAYTM_DB_URL / MERCHANT_DB_URL into the services'
   .env files (git-ignored). Passwords are never printed.
5. Checks each service role can reach its own schema and NOT the other one.

Re-running is safe. Flags: --skip-load, --keep-service-passwords (reuse URLs already in the service .env files).
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

try:
    import psycopg
    from psycopg import sql
except ImportError:
    sys.exit('psycopg missing. Run:  python -m pip install "psycopg[binary]" psycopg-pool pandas pytest')

ROOT = Path(__file__).resolve().parents[2]
REF = "ijitntwpnqwkjrboweky"
HOSTS = [f"aws-{i}-ap-south-1.pooler.supabase.com" for i in (0, 1, 2)]
SUPA_ENV = ROOT / "supabase" / ".env"
SERVICES = {
    "paytm_svc": (ROOT / "services" / "paytm_agent", "PAYTM_DB_URL", "paytm", "merchant"),
    "merchant_svc": (ROOT / "services" / "merchant_agent", "MERCHANT_DB_URL", "merchant", "paytm"),
}


def read_env(path: Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip()
    return out


def upsert_env(path: Path, values: dict[str, str], template: Path | None = None) -> None:
    lines = path.read_text().splitlines() if path.exists() else (
        template.read_text().splitlines() if template and template.exists() else [])
    seen = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*#?\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in values and m.group(1) not in seen:
            lines[i] = f"{m.group(1)}={values[m.group(1)]}"
            seen.add(m.group(1))
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def git_ignored(path: Path) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=ROOT)
    return r.returncode == 0


def try_connect(url: str) -> str | None:
    try:
        with psycopg.connect(url, connect_timeout=8, prepare_threshold=None) as c:
            c.execute("select 1")
        return None
    except Exception as e:  # noqa: BLE001
        return str(e).splitlines()[0]


def owner_url() -> str:
    existing = read_env(SUPA_ENV).get("SUPABASE_DB_URL", "")
    if existing and "<" not in existing and try_connect(existing) is None:
        print("✓ supabase/.env already has a working owner connection")
        return existing
    pw = getpass.getpass("Supabase DATABASE password (Dashboard → Project Settings → Database; input hidden): ")
    if not pw:
        sys.exit("No password entered.")
    last = ""
    for host in HOSTS:
        url = f"postgresql://postgres.{REF}:{quote(pw, safe='')}@{host}:5432/postgres"
        err = try_connect(url)
        if err is None:
            upsert_env(SUPA_ENV, {"SUPABASE_DB_URL": url})
            print(f"✓ connected via {host}; saved to supabase/.env (git-ignored: {git_ignored(SUPA_ENV)})")
            return url
        last = err
        if "password authentication failed" in err:
            sys.exit("✗ Wrong database password. Reset it under Project Settings → Database, then re-run.")
    sys.exit(f"✗ Could not reach the Supabase pooler ({last}). Is the project paused? Restore it in the dashboard.")


def scram_verifier(password: str, iterations: int = 4096) -> str:
    salt = os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def set_service_roles(owner: str, keep: bool) -> dict[str, str]:
    host = urlsplit(owner).hostname
    urls = {}
    with psycopg.connect(owner, autocommit=True, prepare_threshold=None) as c:
        for role, (svc_dir, key, _, _) in SERVICES.items():
            current = read_env(svc_dir / ".env").get(key, "")
            if keep and current and "<" not in current and try_connect(current) is None:
                urls[role] = current
                print(f"✓ {role}: kept existing password")
                continue
            pw = secrets.token_urlsafe(24)
            c.execute(sql.SQL("alter role {} with login password {}").format(
                sql.Identifier(role), sql.Literal(scram_verifier(pw))))
            urls[role] = f"postgresql://{role}.{REF}:{pw}@{host}:6543/postgres"
            print(f"✓ {role}: new random password set (not shown)")
    for role, (svc_dir, key, _, _) in SERVICES.items():
        upsert_env(svc_dir / ".env", {"USE_SUPABASE": "true", key: urls[role]}, svc_dir / ".env.example")
        print(f"✓ wrote USE_SUPABASE=true and {key} to {svc_dir.relative_to(ROOT)}/.env "
              f"(git-ignored: {git_ignored(svc_dir / '.env')})")
    return urls


def check_roles(urls: dict[str, str]) -> bool:
    ok = True
    for role, url in urls.items():
        own, other = SERVICES[role][2], SERVICES[role][3]
        for attempt in range(6):  # the pooler can take a few seconds to see a new password
            err = try_connect(url)
            if err is None or "password authentication failed" not in err:
                break
            time.sleep(3)
        if err:
            print(f"✗ {role} cannot connect: {err}")
            ok = False
            continue
        with psycopg.connect(url, autocommit=True, prepare_threshold=None) as c:
            n = c.execute(sql.SQL("select count(*) from {}.{}").format(
                sql.Identifier(own), sql.Identifier("scenarios"))).fetchone()[0]
            try:
                c.execute(sql.SQL("select 1 from {}.scenarios limit 1").format(sql.Identifier(other)))
                print(f"✗ {role} can read the {other} schema: boundary broken")
                ok = False
            except psycopg.errors.InsufficientPrivilege:
                print(f"✓ {role}: reads {own} ({n} scenarios), blocked from {other}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-load", action="store_true")
    ap.add_argument("--keep-service-passwords", action="store_true")
    a = ap.parse_args()

    owner = owner_url()
    if not a.skip_load:
        print("… loading data (≈10 s)")
        r = subprocess.run([sys.executable, str(ROOT / "supabase" / "seed" / "load_seed.py")],
                           env={**os.environ, "SUPABASE_DB_URL": owner})
        if r.returncode != 0:
            return r.returncode
    urls = set_service_roles(owner, a.keep_service_passwords)
    ok = check_roles(urls)
    print("\nDONE ✓  Restart both services to pick up USE_SUPABASE=true." if ok else "\nFinished with errors (see ✗ above).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
