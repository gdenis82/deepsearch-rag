#!/bin/sh
# entrypoint.sh
set -e

echo "[entrypoint] Running Alembic migrations..."

# --- Настройки ожидания БД  ---
DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_TIMEOUT="${DB_TIMEOUT:-15}"
RETRY_DELAY="${RETRY_DELAY:-3}"

# --- Функция: ждать, пока хост:порт станут доступны (через Python) ---
wait_for_db() {
  echo "[entrypoint] Waiting for DB ($DB_HOST:$DB_PORT) to accept TCP connections..."


  if ! timeout "$DB_TIMEOUT" sh -c "
      while ! python3 -c \"import socket; s = socket.create_connection(('$DB_HOST', $DB_PORT), timeout=1); s.close()\" 2>/dev/null; do
        echo \"[entrypoint] DB not reachable yet — retrying in $RETRY_DELAY s...\"
        sleep $RETRY_DELAY
      done
    "; then
    echo "[entrypoint] ❌ DB did not become reachable within ${DB_TIMEOUT}s"
    return 1
  fi

  echo "[entrypoint] ✅ DB is reachable!"
  return 0
}

# Ждём, пока БД запустится
if ! wait_for_db; then
  echo "[entrypoint] ❌ Critical: Cannot connect to DB ($DB_HOST:$DB_PORT). Exiting."
  exit 1
fi

# --- Теперь запускаем миграции с повторами ---
attempt=0
max_attempts=5
until alembic upgrade head; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "[entrypoint] Alembic upgrade failed after $max_attempts attempts. Exiting."
    exit 1
  fi
  echo "[entrypoint] DB rejected connection or not ready (attempt $attempt/$max_attempts). Retrying in 3s..."
  sleep 3
done

echo "[entrypoint] ✅ Migrations applied. Starting app..."
exec "$@"