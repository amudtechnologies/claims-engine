#!/bin/sh
# Container entrypoint: brings the Django transactional tables up to date,
# does a blocking first sync of the NIT-search Parquet cache so the app
# never serves "not synced" on a cold start, then keeps re-syncing it in the
# background on an interval — core_cache.py is explicit that this has to be
# decoupled from the request path (a live S3 point query takes 15-50s).
set -eu

cd "$(dirname "$0")"

uv run --no-sync python manage.py migrate --noinput

uv run --no-sync python manage.py sync_core_cache \
  || echo "startup sync_core_cache failed; NIT search will report unsynced until a background sync succeeds" >&2

(
  while true; do
    sleep "${CORE_CACHE_SYNC_INTERVAL_SECONDS:-3600}"
    uv run --no-sync python manage.py sync_core_cache \
      || echo "background sync_core_cache failed" >&2
  done
) &

exec uv run --no-sync gunicorn amud_site.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${GUNICORN_WORKERS:-2}"
