# The whole demo in ONE container: frontend + Sarvam (8001) + Paytm (8002) + Merchant (8003), served on one port
# by deploy/gateway.py. Railway: New Project -> Deploy from GitHub repo -> it builds this file. See deploy/README.md.

# ---- 1. build the frontend (it imports ../../data/seed at build time) ----
FROM node:20-slim AS web
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci --no-audit --no-fund --loglevel=error
COPY frontend/ frontend/
COPY data/seed/ data/seed/
# Same-origin API paths served by the gateway: the browser only ever talks to this one domain.
ENV VITE_SARVAM_URL=/svc/sarvam VITE_PAYTM_URL=/svc/paytm VITE_MERCHANT_URL=/svc/merchant
# Optional, public: Supabase Realtime (read-only anon key). Railway passes service variables to declared ARGs.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_MID=PAYTM_MERCH_8821
RUN cd frontend && npm run build

# ---- 2. the three Python services + gateway ----
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RUN_IN_CONTAINER=1
WORKDIR /app
COPY requirements.txt ./
COPY services/sarvam_service/requirements.txt services/sarvam_service/
COPY services/paytm_agent/requirements.txt services/paytm_agent/
COPY services/merchant_agent/requirements.txt services/merchant_agent/
RUN pip install -r requirements.txt
# Repo layout is kept, so merchant_agent finds /app/data/seed and Person 1's sample PNGs by itself.
COPY data/seed/ data/seed/
COPY services/ services/
COPY deploy/gateway.py deploy/
COPY run.py ./
COPY --from=web /src/frontend/dist frontend/dist
EXPOSE 8080
# In-memory demo state: run exactly ONE replica.
CMD ["python", "run.py", "serve"]
