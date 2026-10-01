#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required (use your Neon connection string)." >&2
  exit 1
fi

# Render's free web plan has no pre-deploy command or shell. These operations
# are idempotent and run before accepting traffic after each cold start.
python scripts/apply_schema.py
python manage.py migrate --noinput
python manage.py seed_demo

if [[ "${BOOTSTRAP_ONLY:-0}" == "1" ]]; then
  exit 0
fi

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers 1 --threads 4 --timeout 60
