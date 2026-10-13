#!/bin/sh
set -e
cd /app

if [ ! -f .env ]; then
    echo "[ERROR] /app/.env not found. Create .env next to docker-compose.yml before starting." >&2
    exit 1
fi

cmd="${1:-auto}"
[ $# -gt 0 ] && shift

case "$cmd" in
    auto)
        exec python auto_setup.py --no-pause "$@" ;;
    run)
        exec python auto_setup.py --no-pause --run "$@" ;;
    check|status|setup-triggers|sync-missing|test-connection|validate-schemas)
        exec python setup.py "--$cmd" "$@" ;;
    force-sync)
        exec python replicator/src/manual_sync.py --force "$@" ;;
    -*)
        exec python auto_setup.py --no-pause "$cmd" "$@" ;;
    *)
        exec "$cmd" "$@" ;;
esac
