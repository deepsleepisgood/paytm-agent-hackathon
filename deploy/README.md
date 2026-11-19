# Deploying: ONE Railway service (recommended)

```
Browser ──► https://<your-app>.up.railway.app  (one container, one port)
              /                → the built frontend
              /svc/merchant/…  → merchant_agent (8003) ─┬─► sarvam_service (8001) ──► api.sarvam.ai
              /svc/paytm/…     → paytm_agent    (8002) ◄┘
              /console         → Paytm employee console
              /healthz         → 200 when all three services are up
```

The root `Dockerfile` builds the frontend and runs all three services behind `deploy/gateway.py`. The browser
only talks to one origin, so there is **no Vercel, no CORS and no cross-service URLs to wire up**. The services
reach each other on 127.0.0.1 inside the container, exactly as on your laptop. Before deploying, run the same
thing locally with `python run.py prod` (http://localhost:8080) or `python run.py smoke`.

## Steps
1. Push the repo to GitHub. `git status` must **not** list `.env` (the root `.gitignore` ignores it).
2. Railway → **New Project → Deploy from GitHub repo** → pick this repo. Railway finds the root `Dockerfile`.
   Leave Root Directory empty.
3. **Variables** (Service → Variables → Raw Editor):
   ```
   PORT=8080
   SARVAM_API_KEY=<your Sarvam key>
   SARVAM_MODE=auto
   SARVAM_FALLBACK_TO_MOCK=true
   # Sarvam TTS needs 4-8 s per reply; with the 5 s default the app beeps instead of speaking
   SARVAM_LATENCY_BUDGET=12
   # optional: Supabase Realtime badge in the frontend (public read-only key; used at BUILD time)
   VITE_SUPABASE_URL=https://ijitntwpnqwkjrboweky.supabase.co
   VITE_SUPABASE_ANON_KEY=<publishable key>
   # optional: backends write to Supabase (needs the role passwords, supabase/README.md step 1)
   # USE_SUPABASE=true
   # PAYTM_DB_URL=postgresql://paytm_svc.<ref>:<pw>@<pooler-host>:6543/postgres
   # MERCHANT_DB_URL=postgresql://merchant_svc.<ref>:<pw>@<pooler-host>:6543/postgres
   ```
4. **Settings:**
   - **Networking → Generate Domain**, target port **8080**.
   - **Healthcheck path:** `/healthz`.
   - **Replicas: 1.** The demo state is in memory, so a second replica would split it.
   - **Region:** Southeast Asia (Singapore), the closest to Sarvam's API.
5. Open `https://<your-app>.up.railway.app`. The app switches itself to *Live services*. The console is at
   `/console`. Before each demo run, press **Reset** in the app.

Changing a `VITE_*` variable needs a redeploy, because those values are baked into the frontend at build time.
Every push to the connected branch redeploys automatically, and a redeploy resets the demo state, so don't push
during the demo.

---

# Alternative (not needed): Vercel (frontend) + three Railway services

```
Browser ──► Vercel: frontend (Vite static build)
              │  VITE_MERCHANT_URL ───────► Railway: merchant-agent (8003) ──► sarvam-service (8001) ──► api.sarvam.ai
              └─ VITE_PAYTM_URL (ledger) ─► Railway: paytm-agent    (8002) ◄─┘
```

The browser calls only **8003** and **8002** (`/ledger`). **8001** is called only by 8003, server to server.
It needs no browser CORS entry, and `VITE_SARVAM_URL` is unused by today's frontend.

Nothing in any service folder was changed for deployment. Everything lives in `deploy/`, plus the root
`.dockerignore`, `.gitignore` and `.env.example`.

## 0. Before you start
- Push the repo to GitHub, including `deploy/` and `.dockerignore`.
- Make sure `git status` does **not** list `.env` (the root `.gitignore` ignores it).
- Have the Sarvam key ready. It goes **only** on `sarvam-service`.

## 1. Railway: three services from one repo

Create one Railway project, then three services, each with **+ New → GitHub Repo → this repo**.
Name them exactly as below, because the `${{…}}` references in step 1b depend on these names.

| Service name     | `RAILWAY_DOCKERFILE_PATH`          | `PORT` | Watch paths                                                               |
|------------------|------------------------------------|--------|---------------------------------------------------------------------------|
| `sarvam-service` | `deploy/sarvam_service.Dockerfile` | 8001   | `services/sarvam_service/**`, `deploy/sarvam_service.Dockerfile`          |
| `paytm-agent`    | `deploy/paytm_agent.Dockerfile`    | 8002   | `services/paytm_agent/**`, `deploy/paytm_agent.Dockerfile`                |
| `merchant-agent` | `deploy/merchant_agent.Dockerfile` | 8003   | `services/merchant_agent/**`, `data/seed/**`, `deploy/merchant_agent.Dockerfile` |

### 1a. Service settings (all three)
- **Root Directory: leave empty.** Every Dockerfile builds from the repo root. `merchant-agent` needs `data/seed/`,
  which is outside its folder.
- **Region:** Southeast Asia (Singapore) is closest to Sarvam's API in India. 8003 → 8001 → Sarvam must finish
  within 8003's 6 s timeout.
- **Healthcheck path:** `/health`.
- **Replicas: 1.** 8003 and 8002 keep demo state in memory, so a second replica would split it.
- **Networking → Generate Domain**, with target port = the `PORT` above.
- Railway's `railway.json` "config as code" is deprecated (it only keeps working for older services until
  2026-12-01), so these settings are made in the dashboard instead.

### 1b. Variables (Service → Variables → Raw Editor, paste)

**sarvam-service**
```
RAILWAY_DOCKERFILE_PATH=deploy/sarvam_service.Dockerfile
PORT=8001
SARVAM_API_KEY=<your Sarvam key>
SARVAM_MODE=auto
SARVAM_FALLBACK_TO_MOCK=true
CORS_ORIGINS=http://localhost:3000
```

**paytm-agent**
```
RAILWAY_DOCKERFILE_PATH=deploy/paytm_agent.Dockerfile
PORT=8002
SEED_MID=PAYTM_MERCH_8821
ALLOWED_ORIGINS=https://<your-vercel-project>.vercel.app,http://localhost:3000
```

**merchant-agent**
```
RAILWAY_DOCKERFILE_PATH=deploy/merchant_agent.Dockerfile
PORT=8003
SARVAM_SERVICE_URL=https://${{sarvam-service.RAILWAY_PUBLIC_DOMAIN}}
PAYTM_AGENT_URL=https://${{paytm-agent.RAILWAY_PUBLIC_DOMAIN}}
CORS_EXTRA_ORIGINS=https://<your-vercel-project>.vercel.app
UPSTREAM_TIMEOUT_S=6
DOC_EXTRACT_TIMEOUT_S=30
UPSTREAM_CIRCUIT_COOLDOWN_S=10
UTTERANCE_FAST_PATH=1
```
`RAILWAY_PUBLIC_DOMAIN` is a bare hostname, so the `https://` prefix is required. Do not set `DATASET_DIR`:
the image keeps the repo layout, so 8003 finds `/app/data/seed` by itself.

**Supabase (optional; persistence + the frontend's Realtime feed, see `supabase/README.md`).** Both images
already include `psycopg`. Add these only once you have the two role passwords from `supabase/README.md`
step 1. Without them, leave `USE_SUPABASE` unset and the services run in memory.
```
# paytm-agent
USE_SUPABASE=true
PAYTM_DB_URL=postgresql://paytm_svc.ijitntwpnqwkjrboweky:<paytm_svc-password>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
# merchant-agent
USE_SUPABASE=true
MERCHANT_DB_URL=postgresql://merchant_svc.ijitntwpnqwkjrboweky:<merchant_svc-password>@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
```
Use the transaction pooler (port 6543), as above, and copy the exact host from Supabase → Connect. The direct
`db.<ref>.supabase.co` host is IPv6-only. Each service gets only its own role. Never put the service-role key
or the `postgres` owner URL on Railway.

### 1c. Check
```
curl https://<sarvam-service>.up.railway.app/health    # "mode":"live","api_key_configured":true
curl https://<paytm-agent>.up.railway.app/health       # {"ok":true,...}
curl https://<merchant-agent>.up.railway.app/health    # sarvam_url/paytm_url = the Railway https URLs, dataset.found=true
```
The 8002 employee console is served by 8002 itself: `https://<paytm-agent>.up.railway.app/`.

## 2. Vercel: frontend

**Add New → Project → import the same repo**, then:
- **Root Directory:** `frontend`. Framework preset **Vite** is auto-detected (build `npm run build`, output `dist`).
- Keep **"Include files outside the root directory in the Build Step"** enabled (the default).
  `src/seedSharma.js` imports `../../data/seed/*`.
- **Environment Variables** (Production; add Preview too if you use preview links):
  ```
  VITE_MERCHANT_URL=https://<merchant-agent>.up.railway.app
  VITE_PAYTM_URL=https://<paytm-agent>.up.railway.app
  VITE_SARVAM_URL=https://<sarvam-service>.up.railway.app
  VITE_MID=PAYTM_MERCH_8821
  # Supabase Realtime (public read-only anon/publishable key; RLS allows SELECT on 8 demo tables only)
  VITE_SUPABASE_URL=https://ijitntwpnqwkjrboweky.supabase.co
  VITE_SUPABASE_ANON_KEY=<publishable key, Supabase → Project Settings → API>
  ```
  These are baked in at **build** time. After changing one, **Redeploy** for it to take effect.
- No `vercel.json` is needed: the app has no client-side routes.

## 3. Order (the URLs depend on each other)
1. Deploy the three Railway services and generate their domains.
2. Create the Vercel project with the `VITE_*` URLs from step 1.
3. Put the Vercel production domain into `ALLOWED_ORIGINS` (paytm-agent) and `CORS_EXTRA_ORIGINS`
   (merchant-agent). Railway redeploys them automatically.
4. Open the Vercel URL. Before each demo run, press the app's reset, or call
   `POST https://<merchant-agent>.up.railway.app/reset?cascade=true`.

## Gotchas
- **Preview deployments** get a different `*.vercel.app` URL, and CORS blocks it unless you add that origin too.
  Demo from the production URL.
- **State resets on every redeploy** of 8002 or 8003 (in memory by design). Don't push during the demo.
- **Secrets:** the Sarvam key belongs only in Railway's `sarvam-service` variables and your local root `.env`.
  `VITE_*` values are public: they end up in the browser bundle.
- **Sarvam credits:** set `SARVAM_MODE=mock` on `sarvam-service` while rehearsing, then switch back to `auto`.
- **Supabase free tier pauses after a week without traffic.** Open the dashboard and restore the project
  before the demo. If it's down, the services fall back to memory after one log line (30 s circuit breaker).

## Local run (one shared root `.env`)
Copy `.env.example` to `.env` at the repo root and add the key. 8001 and 8002 find it through `load_dotenv()`,
and 8003 reads it after its own `.env`. A per-service `.env` still wins for that service.
```
cd services/sarvam_service && uvicorn app.main:app --port 8001
cd services/paytm_agent    && uvicorn app.main:app --port 8002
cd services/merchant_agent && uvicorn main:app --port 8003
cd frontend && npm run dev            # http://localhost:3000, defaults to the localhost URLs
```
