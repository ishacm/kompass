#!/bin/sh
# Start-up for a stateless (free) host: rebuild the context layer from committed CSVs, then serve.
set -e
SRC=data/accounts_public.csv
[ -f "$SRC" ] || SRC=data/seed_accounts.csv
python -m kompass.ingest "$SRC"
python -m kompass.score
python -m kompass.inbound.retention || true
exec uvicorn kompass.inbound.app:app --host 0.0.0.0 --port "${PORT:-8080}"
