#!/bin/sh
# Lynceus container entrypoint.
# 1. First boot (no inspection-* records in the storage dir): seed the 24-truck
#    sample shift so the shift report and ledger are not empty. The seeder pins
#    the offline stub (no network, no key) and only ever deletes inspection-* dirs.
# 2. Start the app on ${PORT:-8020}, bound to 0.0.0.0. `exec` makes the server
#    PID 1 so docker stop's SIGTERM reaches it.
set -eu

: "${LYNCEUS_STORAGE_DIR:=/data/runs}"
export LYNCEUS_STORAGE_DIR
: "${PORT:=8020}"
export PORT

mkdir -p "$LYNCEUS_STORAGE_DIR"

if ls -d "$LYNCEUS_STORAGE_DIR"/inspection-* >/dev/null 2>&1; then
    echo "lynceus: records found in $LYNCEUS_STORAGE_DIR, not seeding"
else
    echo "lynceus: empty storage, seeding the sample shift into $LYNCEUS_STORAGE_DIR"
    python /app/backend/scripts/seed_demo.py --reset --shift
fi

exec python -m lynceus.main
