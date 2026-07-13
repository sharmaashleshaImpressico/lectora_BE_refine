#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "[entrypoint] RUN_MIGRATIONS=1 — running alembic upgrade head..."
    alembic upgrade head
fi

exec "$@"
