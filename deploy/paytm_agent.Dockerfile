# Person 2 - Paytm agent + employee console (8002). Build context: repo root.
# Railway: set RAILWAY_DOCKERFILE_PATH=deploy/paytm_agent.Dockerfile on the service.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY services/paytm_agent/requirements.txt .
RUN pip install -r requirements.txt
COPY services/paytm_agent/ .
EXPOSE 8002
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8002}"]
