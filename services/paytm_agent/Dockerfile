# Build from the REPO ROOT so data/paytm comes along:
#   docker build -f services/paytm_agent/Dockerfile -t paytm-agent .
#   docker run -p 8002:8002 -e ALLOWED_ORIGINS=https://your-frontend paytm-agent
#
# Without data/paytm the service still runs: UTR lookups fall back to the seeded
# references. It is copied in because losing 6,500 payments would quietly turn almost
# every real lookup into "I cannot find this payment in your account".
FROM python:3.13-slim

WORKDIR /srv
COPY services/paytm_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/paytm_agent/app ./app
COPY data/paytm ./data/paytm
ENV PAYTM_DATA_DIR=/srv/data/paytm

# The host decides the port; 8002 is only the contract's local default.
ENV PORT=8002
EXPOSE 8002
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
