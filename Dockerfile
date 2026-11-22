FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV KOMPASS_DB=/data/kompass.duckdb KOMPASS_LLM=live
EXPOSE 8080
# Inbound form + Slack review endpoint. Retention runs on start and daily via the host's cron.
CMD python -m kompass.inbound.retention && uvicorn kompass.inbound.app:app --host 0.0.0.0 --port ${PORT:-8080}
