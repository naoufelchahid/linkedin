#!/usr/bin/env bash
# PostgreSQL et Thunderbird partagent uniquement le socket Unix de cette recette.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d)
mkdir "$work/socket"
chmod 777 "$work/socket"
pg=""
cleanup() {
    if [[ -n "$pg" ]]; then docker rm -fv "$pg" >/dev/null; fi
    rm -rf "$work"
}
trap cleanup EXIT
pg=$(docker run -d --rm --network none -v "$work/socket:/fixture-socket" -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17 -c unix_socket_directories=/var/run/postgresql,/fixture-socket)
export PGHOST="$work/socket" PGDATABASE=postgres PGUSER=postgres
unset PGOPTIONS PGHOSTADDR PGSERVICE PGPORT
for _ in {1..60}; do
    if [[ $(docker exec "$pg" cat /proc/1/comm) == postgres ]] && pg_isready -q; then break; fi
    sleep 1
done
psql -Xqf "$root/db/bootstrap.sql" >/dev/null
psql -Xqf "$root/db/migrate.sql" >/dev/null
PYTHONPATH="$root/jobs/graphe2/src" unshare --user --map-current-user --net --keep-caps \
    "${PYTHON:-$root/jobs/graphe2/.venv/bin/python}" "$root/jobs/graphe2/tests/recette_confirmations/run.py"
