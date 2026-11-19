#!/usr/bin/env sh
# Container entry point: migrate first, then serve.
#
# Migrations are not optional at startup. A container that serves an API
# against a schema older than its code answers with 500s that look like
# application bugs; failing here makes the deployment error legible.
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

echo "Applying database migrations..."
alembic upgrade head

echo "Starting API on port ${PORT:-8000}..."
exec uvicorn api.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
