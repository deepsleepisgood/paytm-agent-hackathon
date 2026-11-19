# Person 1 - Sarvam service (8001). Build context: repo root.
# Railway: set RAILWAY_DOCKERFILE_PATH=deploy/sarvam_service.Dockerfile on the service.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY services/sarvam_service/requirements.txt .
RUN pip install -r requirements.txt
COPY services/sarvam_service/ .
EXPOSE 8001
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
