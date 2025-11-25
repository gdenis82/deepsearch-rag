#!/bin/sh
# entrypoint.sh
set -e

echo "[entrypoint] Running Alembic migrations..."

# Retry alembic upgrade until DB is ready (max 20 attempts)
attempt=0
max_attempts=20
until alembic upgrade head; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "[entrypoint] Alembic upgrade failed after $attempt attempts. Exiting."
    exit 1
  fi
  echo "[entrypoint] DB not ready yet (attempt $attempt/$max_attempts). Waiting..."
  sleep 3
done

echo "[entrypoint] Migrations applied. Starting app..."

exec "$@"
