"""One public port for the whole demo (used by `python run.py prod|serve` and the root Dockerfile).

    /                 the built frontend (frontend/dist)
    /svc/sarvam/...   -> sarvam_service  (8001, internal)
    /svc/paytm/...    -> paytm_agent     (8002, internal)
    /svc/merchant/... -> merchant_agent  (8003, internal)
    /console          -> Person 2's employee console (8002 "/"); its own absolute calls
                         (/tickets, /metrics, /summaries) are routed to 8002 as well
    /healthz          -> 200 only when all three services answer /health

The frontend is built with VITE_*_URL=/svc/<name>, so the browser only ever talks to this one
origin: no CORS, one domain, one deployment. The services keep talking to each other directly on
127.0.0.1, exactly as in local dev.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

UPSTREAMS = {
    "sarvam": os.getenv("SARVAM_SERVICE_URL", "http://127.0.0.1:8001").rstrip("/"),
    "paytm": os.getenv("PAYTM_AGENT_URL", "http://127.0.0.1:8002").rstrip("/"),
    "merchant": os.getenv("MERCHANT_AGENT_URL", "http://127.0.0.1:8003").rstrip("/"),
}
DIST = Path(os.getenv("FRONTEND_DIST") or Path(__file__).resolve().parents[1] / "frontend" / "dist")
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
# Hop-by-hop headers (RFC 9110 §7.6.1) plus the ones httpx recomputes.
_DROP_REQ = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
             "transfer-encoding", "upgrade", "host", "content-length"}
_DROP_RESP = _DROP_REQ | {"content-encoding"}  # httpx already decompressed the body

client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(_app):
    global client
    # Audio and document extraction can take ~45 s upstream (Sarvam Vision budget is 25-30 s).
    client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0))
    yield
    await client.aclose()


async def _forward(request: Request, base: str, path: str) -> Response:
    url = f"{base}/{path.lstrip('/')}"
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _DROP_REQ]
    try:
        r = await client.request(request.method, url, params=request.query_params, headers=headers,
                                 content=await request.body())
    except httpx.HTTPError as exc:
        return JSONResponse({"error": {"code": "UPSTREAM_DOWN", "retryable": True,
                                       "message": f"{base} unreachable ({type(exc).__name__})"}}, status_code=502)
    out = {k: v for k, v in r.headers.items() if k.lower() not in _DROP_RESP}
    return Response(r.content, status_code=r.status_code, headers=out)


async def service(request: Request) -> Response:
    base = UPSTREAMS.get(request.path_params["svc"])
    if base is None:
        return JSONResponse({"error": {"code": "UNKNOWN_SERVICE", "message": "use /svc/sarvam|paytm|merchant"}},
                            status_code=404)
    return await _forward(request, base, request.path_params.get("path", ""))


async def console(request: Request) -> Response:
    return await _forward(request, UPSTREAMS["paytm"], "/")


async def console_api(request: Request) -> Response:
    return await _forward(request, UPSTREAMS["paytm"], request.url.path)


async def healthz(_request: Request) -> Response:
    async def one(name: str, base: str):
        try:
            r = await client.get(f"{base}/health", timeout=3.0)
            return name, r.status_code == 200
        except httpx.HTTPError:
            return name, False

    results = dict(await asyncio.gather(*(one(n, b) for n, b in UPSTREAMS.items())))
    ok = all(results.values()) and (DIST / "index.html").is_file()
    return JSONResponse({"ok": ok, "services": results, "frontend": (DIST / "index.html").is_file()},
                        status_code=200 if ok else 503)


routes = [
    Route("/healthz", healthz),
    Route("/svc/{svc}", service, methods=METHODS),
    Route("/svc/{svc}/{path:path}", service, methods=METHODS),
    Route("/console", console),
    Route("/tickets", console_api, methods=METHODS),
    Route("/tickets/{rest:path}", console_api, methods=METHODS),
    Route("/metrics", console_api),
    Route("/summaries", console_api),
    Route("/summaries/{rest:path}", console_api),
]
if (DIST / "index.html").is_file():
    routes.append(Mount("/", app=StaticFiles(directory=DIST, html=True)))
else:
    async def not_built(_request: Request) -> Response:
        return JSONResponse({"error": f"frontend not built: {DIST} missing. Run `python run.py prod`."},
                            status_code=503)
    routes.append(Route("/", not_built))

app = Starlette(routes=routes, lifespan=lifespan)
