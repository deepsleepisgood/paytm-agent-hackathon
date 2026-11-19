#!/usr/bin/env python3
"""One command for the whole Paytm x Sarvam demo.

    python run.py            DEV: 8001 Sarvam + 8002 Paytm + 8003 Merchant + frontend on http://localhost:3000
    python run.py prod       ONE PORT: builds the frontend, serves app + all APIs on http://localhost:8080
                             (exactly what the deployment runs)
    python run.py test       every test suite (3 services) + a frontend production build
    python run.py smoke      starts the one-port stack, plays the demo through it, stops it
                             (Sarvam in mock mode; add --live to use your real key)
    python run.py eval       short live eval: 23 Hindi/English questions -> right intent, right fact, right language
    python run.py stop       frees ports 3000, 8001-8003 and 8080 if something was left running
    python run.py setup      (re)install dependencies only
    python run.py serve      what the Docker image runs: like prod, without building

The first run creates .venv (Python 3.11 if available) and installs everything, so `python run.py` is
all you need. Settings come from the repo-root .env (copy .env.example). Ctrl+C stops everything.
Only the standard library is used here, so this file runs before anything is installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
IN_CONTAINER = os.getenv("RUN_IN_CONTAINER") == "1"
SERVICES = [  # name, port, folder, ASGI app
    ("sarvam", 8001, ROOT / "services" / "sarvam_service", "app.main:app"),
    ("paytm", 8002, ROOT / "services" / "paytm_agent", "app.main:app"),
    ("merchant", 8003, ROOT / "services" / "merchant_agent", "main:app"),
]
FRONTEND_PORT = 3000
GATEWAY_PORT_DEFAULT = 8080
MID = "PAYTM_MERCH_8821"
COLORS = {"sarvam": "35", "paytm": "34", "merchant": "32", "frontend": "36", "gateway": "33", "run": "1"}

try:  # Devanagari in logs must not crash a cp1252 Windows console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


def say(name: str, msg: str) -> None:
    print(f"\x1b[{COLORS.get(name, '0')}m[{name:>8}]\x1b[0m {msg}", flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# ----------------------------------------------------------------------------- setup

def _base_python() -> str:
    """Python 3.11 is what the services are built and tested on; 3.12 is fine; else the current one."""
    if os.name == "nt" and shutil.which("py"):
        for v in ("3.11", "3.12"):
            r = subprocess.run(["py", f"-{v}", "-c", "import sys; print(sys.executable)"], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
    for name in ("python3.11", "python3.12"):
        if found := shutil.which(name):
            return found
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10+ is required (3.11 recommended).")
    return sys.executable


def _req_files() -> list[Path]:
    return [ROOT / "requirements.txt"] + [folder / "requirements.txt" for _, _, folder, _ in SERVICES]


def _npm() -> str:
    npm = shutil.which("npm")
    if not npm:
        sys.exit("Node.js (npm) is required for the frontend: https://nodejs.org (v20+).")
    return npm


def setup(force: bool = False) -> None:
    py = venv_python()
    if not py.exists():
        base = _base_python()
        say("run", f"creating .venv with {base}")
        subprocess.run([base, "-m", "venv", str(VENV)], check=True)
    digest = hashlib.sha256(b"".join(p.read_bytes() for p in _req_files())).hexdigest()
    stamp = VENV / ".requirements.sha256"
    if force or not stamp.exists() or stamp.read_text().strip() != digest:
        say("run", "installing Python packages for all three services (first time takes a minute)...")
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r",
                        str(ROOT / "requirements.txt")], check=True)
        stamp.write_text(digest)
    lock, marker = FRONTEND / "package-lock.json", FRONTEND / "node_modules" / ".package-lock.json"
    if force or not marker.exists() or (lock.exists() and lock.stat().st_mtime > marker.stat().st_mtime):
        say("run", "installing frontend packages (npm ci)...")
        subprocess.run([_npm(), "ci", "--no-audit", "--no-fund", "--loglevel=error"], cwd=FRONTEND, check=True)
    if not (ROOT / ".env").exists():
        say("run", "no .env at the repo root: copy .env.example to .env and add SARVAM_API_KEY "
                   "(without it Sarvam runs in mock mode)")


def ensure_venv(argv: list[str]) -> None:
    """Re-run this script inside .venv, so `python run.py` works from any Python."""
    if IN_CONTAINER:
        return
    py = venv_python()
    try:
        inside = py.exists() and Path(sys.executable).resolve() == py.resolve()
    except OSError:
        inside = False
    if inside:
        return
    setup()
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # the child handles Ctrl+C and cleans up
    sys.exit(subprocess.call([str(py), str(Path(__file__).resolve()), *argv]))


# ----------------------------------------------------------------------------- processes

def port_busy(port: int) -> bool:
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            continue
    return False


def _listener_pids(port: int) -> set[int]:
    pids: set[int] = set()
    if os.name == "nt":
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        out += subprocess.run(["netstat", "-ano", "-p", "TCPv6"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
                pids.add(int(parts[4]))
    elif shutil.which("lsof"):
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        pids.update(int(p) for p in out.split())
    return pids - {0, os.getpid()}


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


class Stack:
    def __init__(self) -> None:
        self.procs: list[tuple[str, subprocess.Popen]] = []
        self.stopping = False

    def spawn(self, name: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
        kw: dict = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", bufsize=1, **kw)
        self.procs.append((name, p))
        threading.Thread(target=self._pump, args=(name, p), daemon=True).start()

    @staticmethod
    def _pump(name: str, p: subprocess.Popen) -> None:
        for line in p.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                say(name, line)

    def stop(self) -> None:
        if self.stopping:
            return
        self.stopping = True
        for name, p in reversed(self.procs):
            if p.poll() is None:
                kill_tree(p.pid)
        for _, p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        say("run", "stopped; all ports freed")

    def watch(self) -> int:
        """Block until Ctrl+C (0) or until any process dies (1, and everything else is stopped)."""
        try:
            while True:
                for name, p in self.procs:
                    if p.poll() is not None:
                        say("run", f"{name} exited with code {p.returncode}; stopping everything")
                        return 1
                time.sleep(0.5)
        except KeyboardInterrupt:
            print()
            return 0
        finally:
            self.stop()


def wait_http(url: str, timeout: float = 90.0, stack: Stack | None = None) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if stack and any(p.poll() is not None for _, p in stack.procs):
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return False


def service_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
           # explicit, so a stale value in a service's own .env can't point the agents elsewhere
           "SARVAM_SERVICE_URL": "http://127.0.0.1:8001", "PAYTM_AGENT_URL": "http://127.0.0.1:8002"}
    env.pop("PORT", None)  # PORT belongs to the gateway; 8002 reads PORT for its own settings
    env.update(extra or {})
    return env


def start_services(stack: Stack, host: str, env: dict[str, str]) -> bool:
    for name, port, folder, app in SERVICES:
        stack.spawn(name, [sys.executable, "-m", "uvicorn", app, "--host", host, "--port", str(port)], folder, env)
    for name, port, _, _ in SERVICES:
        if not wait_http(f"http://127.0.0.1:{port}/health", stack=stack):
            say("run", f"{name} did not come up on :{port}; see its log lines above")
            return False
    return True


def check_ports(ports: list[int]) -> None:
    busy = [p for p in ports if port_busy(p)]
    if busy:
        sys.exit(f"Port(s) {', '.join(map(str, busy))} already in use (another copy running?). "
                 f"Free them with:  python run.py stop")


def build_frontend(extra_env: dict[str, str] | None = None) -> None:
    env = {**os.environ,
           # same-origin paths behind deploy/gateway.py (process env beats frontend/.env in Vite)
           "VITE_SARVAM_URL": "/svc/sarvam", "VITE_PAYTM_URL": "/svc/paytm", "VITE_MERCHANT_URL": "/svc/merchant"}
    env.update(extra_env or {})
    say("run", "building the frontend for one-port mode...")
    r = subprocess.run([_npm(), "run", "build", "--", "--logLevel", "warn"], cwd=FRONTEND, env=env)
    if r.returncode:
        sys.exit("frontend build failed")


def start_gateway(stack: Stack, host: str, port: int, env: dict[str, str]) -> bool:
    stack.spawn("gateway", [sys.executable, "-m", "uvicorn", "gateway:app", "--app-dir", str(ROOT / "deploy"),
                            "--host", host, "--port", str(port), "--proxy-headers"],
                # via env, not argv: on Windows the CLI glob-expands a bare "*" into file names
                ROOT, {**env, "FRONTEND_DIST": str(DIST), "FORWARDED_ALLOW_IPS": "*"})
    return wait_http(f"http://127.0.0.1:{port}/healthz", timeout=30, stack=stack)


# ----------------------------------------------------------------------------- commands

def cmd_dev(_args) -> int:
    check_ports([p for _, p, _, _ in SERVICES] + [FRONTEND_PORT])
    stack = Stack()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    if not start_services(stack, "127.0.0.1", service_env()):
        stack.stop()
        return 1
    stack.spawn("frontend", [_npm(), "run", "dev"], FRONTEND, {**os.environ, "BROWSER": "none"})
    if not wait_http(f"http://localhost:{FRONTEND_PORT}/", timeout=60, stack=stack):
        say("run", "frontend did not start")
        stack.stop()
        return 1
    banner([("App", f"http://localhost:{FRONTEND_PORT}"), ("Paytm employee console", "http://localhost:8002/"),
            ("APIs", "8001 Sarvam · 8002 Paytm · 8003 Merchant (each has /health and /docs)")])
    return stack.watch()


def cmd_serve(args, build: bool) -> int:
    port = int(os.getenv("PORT") or args.port or GATEWAY_PORT_DEFAULT)
    if port in (8001, 8002, 8003):
        sys.exit(f"PORT={port} clashes with an internal service port; use 8080.")
    if build:
        build_frontend()
    if not IN_CONTAINER:
        check_ports([p for _, p, _, _ in SERVICES] + [port])
    host = "0.0.0.0" if IN_CONTAINER else "127.0.0.1"
    stack = Stack()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    env = service_env()
    if not (start_services(stack, "127.0.0.1", env) and start_gateway(stack, host, port, env)):
        stack.stop()
        return 1
    banner([("App", f"http://localhost:{port}"), ("Paytm employee console", f"http://localhost:{port}/console"),
            ("Health", f"http://localhost:{port}/healthz"), ("APIs", f"http://localhost:{port}/svc/<sarvam|paytm|merchant>/...")])
    return stack.watch()


def cmd_test(_args) -> int:
    results = []
    for name, _, folder, _ in SERVICES:
        say("run", f"testing {name} ...")
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=folder,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        tail = [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-1:] or ["(no output)"]
        results.append((name, r.returncode == 0, tail[0]))
        if r.returncode:
            print(r.stdout[-4000:], r.stderr[-2000:])
    say("run", "building the frontend (production build check) ...")
    r = subprocess.run([_npm(), "run", "build", "--", "--logLevel", "error", "--outDir",
                        str(ROOT / ".venv" / "frontend-build-check"), "--emptyOutDir"], cwd=FRONTEND,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    results.append(("frontend", r.returncode == 0, "build ok" if r.returncode == 0 else r.stdout[-300:] + r.stderr[-300:]))
    print()
    for name, ok, line in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<9} {line}")
    return 0 if all(ok for _, ok, _ in results) else 1


def _multipart(field: str, filename: str, data: bytes, fields: dict[str, str]) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                 f"Content-Type: image/png\r\n\r\n".encode() + data + b"\r\n")
    return b"".join(parts) + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def cmd_smoke(args) -> int:
    port = args.port or 8089
    build_frontend()
    check_ports([p for _, p, _, _ in SERVICES] + [port])
    extra = {} if args.live else {"SARVAM_MODE": "mock"}
    say("run", "Sarvam: " + ("LIVE (uses your key)" if args.live else "mock (add --live to use your key)"))
    stack = Stack()
    env = service_env(extra)
    if not (start_services(stack, "127.0.0.1", env) and start_gateway(stack, "127.0.0.1", port, env)):
        stack.stop()
        return 1
    base = f"http://127.0.0.1:{port}"
    fails: list[str] = []

    def call(method: str, path: str, body=None, ctype="application/json", raw=False):
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": ctype} if data is not None else {})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                payload = r.read()
                return r.status, (payload if raw else json.loads(payload or b"null"))
        except urllib.error.HTTPError as e:
            payload = e.read()
            return e.code, (payload if raw else {"_error": payload.decode("utf-8", "replace")[:300]})

    def check(name: str, ok: bool, info: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + info) if info and not ok else ''}", flush=True)
        if not ok:
            fails.append(name)

    try:
        print()
        s, h = call("GET", "/healthz")
        check("one port is healthy (3 services + frontend)", s == 200 and h.get("ok"), str(h))
        s, html = call("GET", "/", raw=True)
        check("frontend is served", s == 200 and b'id="root"' in html)
        s, _ = call("POST", "/svc/merchant/reset?cascade=true", {})
        check("reset (merchant + paytm ledger)", s == 200)
        s, b = call("POST", "/svc/merchant/merchant/query",
                    {"text": "Kal ₹1,00,000 sale tha, bank mein ₹95,840 aaya — ₹4,160 kahan kata?", "mid": MID, "consent_granted": True})
        check("settlement: Paytm live, GST ITC ₹261 logged", s == 200 and b.get("paytm_source") == "live"
              and (b.get("gst_itc_logged") or {}).get("amount") == 261, str(b)[:300])
        fake = (FRONTEND / "public" / "demo" / "fake_upi.png").read_bytes()
        body, ctype = _multipart("file", "fake_upi.png", fake, {"doc_type": "upi_screenshot", "mid": MID, "consent_granted": "true"})
        s, b = call("POST", "/svc/merchant/merchant/upload-doc", body, ctype)
        check("fake screenshot: fraud alert raised", s == 200 and bool(b.get("fraud_alert")), str(b)[:300])
        s, b = call("POST", "/svc/merchant/merchant/proactive-shield", {"mid": MID, "scenario": "CASHFLOW_EDI_SWITCH", "consent_granted": True})
        offer = ((b or {}).get("proactive") or {}).get("edi_pause_offer") or {}
        check("cashflow alert asks before acting", s == 200 and offer.get("offer_id") and "रोक दूँ" in b.get("reply_text", ""), str(b)[:300])
        s, b = call("POST", "/svc/merchant/merchant/confirm-edi-pause",
                    {"mid": MID, "consent_granted": True, "offer_id": offer.get("offer_id"), "pause_days": 2})
        s2, led = call("GET", f"/svc/paytm/ledger/{MID}")
        check("merchant says yes -> EDI paused in Paytm's ledger", s == 200 and s2 == 200
              and str((led.get("loan") or {}).get("status", "")).startswith("PAUSED"), str(led)[:300])
        s, csv = call("GET", "/svc/merchant/merchant/khata-export?format=csv", raw=True)
        check("khata CSV export (Tally)", s == 200 and b"Voucher" in csv)
        s, page = call("GET", "/console", raw=True)
        s2, t = call("GET", "/tickets")
        check("Paytm employee console + its API", s == 200 and b"<html" in page.lower() and s2 == 200)
        call("POST", "/svc/merchant/reset?cascade=true", {})
    finally:
        stack.stop()
    print(f"\n  {'ALL PASSED' if not fails else f'{len(fails)} FAILED'}")
    return 0 if not fails else 1


def cmd_eval(_args) -> int:
    """Starts the three services (live Sarvam from .env), runs services/merchant_agent/eval_live.py, stops them."""
    check_ports([p for _, p, _, _ in SERVICES])
    stack = Stack()
    if not start_services(stack, "127.0.0.1", service_env()):
        stack.stop()
        return 1
    if sarvam_status()[1].startswith("LIVE") is False:
        say("run", "Sarvam is in MOCK mode (no key): the eval needs the live LLM and will mostly fail")
    try:
        return subprocess.call([sys.executable, str(ROOT / "services" / "merchant_agent" / "eval_live.py"),
                                "--base", "http://127.0.0.1:8003"], env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    finally:
        stack.stop()


def cmd_stop(_args) -> int:
    ports = [FRONTEND_PORT, 8001, 8002, 8003, GATEWAY_PORT_DEFAULT, 8089]
    for port in ports:
        for pid in _listener_pids(port):
            say("run", f"stopping pid {pid} on :{port}")
            kill_tree(pid)
    time.sleep(1)
    left = [p for p in ports if port_busy(p)]
    say("run", "all ports free" if not left else f"still busy: {left}")
    return 0 if not left else 1


def sarvam_status() -> tuple[str, str]:
    """Shown in the banner: a missing key silently turned voice into canned demo lines before."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=3) as r:
            mode = json.loads(r.read()).get("mode", "unknown")
    except (urllib.error.URLError, OSError, ValueError):
        mode = "down"
    if mode == "live":
        return "Sarvam", "LIVE (speech recognition + Sarvam voice on)"
    return "Sarvam", ("\x1b[41;97m MOCK: no SARVAM_API_KEY in .env \x1b[0m voice recognition and Sarvam voice are OFF "
                      "(the app says so instead of answering). Add the key to .env and restart.")


def banner(rows: list[tuple[str, str]]) -> None:
    rows = rows + [sarvam_status()]
    w = max(len(k) for k, _ in rows)
    print("\n\x1b[1m  Everything is up. Ctrl+C stops it all.\x1b[0m")
    for k, v in rows:
        print(f"  {k:<{w}}  {v}")
    print(flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="dev",
                    choices=["dev", "prod", "serve", "test", "smoke", "eval", "stop", "setup"])
    ap.add_argument("--port", type=int, help="port for prod/serve/smoke (default 8080; smoke 8089)")
    ap.add_argument("--live", action="store_true", help="smoke: use the real Sarvam key instead of mock")
    args = ap.parse_args()
    if args.command == "stop":  # needs nothing installed
        return cmd_stop(args)
    if args.command == "setup":  # works from any Python: it installs into .venv
        setup(force=True)
        return 0
    ensure_venv(sys.argv[1:])
    return {"dev": cmd_dev, "test": cmd_test, "smoke": cmd_smoke, "eval": cmd_eval,
            "prod": lambda a: cmd_serve(a, build=True), "serve": lambda a: cmd_serve(a, build=False)}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
