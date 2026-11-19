# Person 3 - Merchant AI Buddy (8003). Build context: repo root.
# Railway: set RAILWAY_DOCKERFILE_PATH=deploy/merchant_agent.Dockerfile on the service.
# Keeps the repo layout so the service finds <repo>/data/seed with no DATASET_DIR. It also includes Person 1's
# two connector PNGs, so the chargeback PoD works even if 8001 is down.
# State is in memory: run exactly ONE replica.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/services/merchant_agent
COPY services/merchant_agent/requirements.txt .
RUN pip install -r requirements.txt
COPY data/seed/ /app/data/seed/
COPY services/sarvam_service/app/samples/ /app/services/sarvam_service/app/samples/
COPY services/merchant_agent/ .
EXPOSE 8003
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8003}"]
