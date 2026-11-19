# Deploying: Vercel (frontend) + Railway (3 services)

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

## Local run (one shared root `.env`)
Copy `.env.example` to `.env` at the repo root and add the key. 8001 and 8002 find it through `load_dotenv()`,
and 8003 reads it after its own `.env`. A per-service `.env` still wins for that service.
```
cd services/sarvam_service && uvicorn app.main:app --port 8001
cd services/paytm_agent    && uvicorn app.main:app --port 8002
cd services/merchant_agent && uvicorn main:app --port 8003
cd frontend && npm run dev            # http://localhost:3000, defaults to the localhost URLs
```
