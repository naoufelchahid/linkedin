#!/usr/bin/env bash
# Usage : migration_rehearsal.sh /chemin/vers/bundle-ticket-01
set -euo pipefail
umask 077
root=$(cd "$(dirname "$0")/../.." && pwd)
bundle=$(realpath "${1:?bundle restauré du ticket 1 requis}")
python=${PYTHON:-"$root/jobs/graphe2/.venv/bin/python"}
work=$(mktemp -d)
mkdir "$work/socket"
chmod 777 "$work/socket"
pg=""
cleanup() {
    if [[ -n "$pg" ]]; then docker rm -fv "$pg" >/dev/null; fi
    rm -rf "$work"
}
trap cleanup EXIT
pg=$(docker run -d --rm --log-driver=none --network none -v "$work/socket:/fixture-socket" \
    -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17 -c unix_socket_directories=/var/run/postgresql,/fixture-socket)
unset PGSERVICE PGSERVICEFILE PGHOSTADDR PGPORT PGOPTIONS PGPASSWORD
export PGHOST="$work/socket" PGUSER=postgres PGDATABASE=rehearsal_21
for _ in {1..60}; do
    if [[ $(docker exec "$pg" cat /proc/1/comm) == postgres ]] && pg_isready -q; then break; fi
    sleep 1
done
createdb rehearsal_21
psql -Xqf "$root/db/bootstrap.sql" >/dev/null
psql -Xqf "$root/db/migrate.sql" >/dev/null
export PYTHONPATH="$root/jobs/graphe1/src:$root/jobs/graphe2/src"
createdb rehearsal_cv
PGDATABASE=rehearsal_cv psql -Xqf "$root/db/bootstrap.sql" >/dev/null
mkdir "$work/previous"
git -C "$root" archive 739ebe1 db | tar -x -C "$work/previous"
PGDATABASE=rehearsal_cv psql -Xqf "$work/previous/db/migrate.sql" >/dev/null
PGDATABASE=rehearsal_cv "$python" "$root/db/tests/cycle_document_replay.py"
"$python" "$root/db/tests/restored_history.py" "$bundle" "$work/rollback"
if [[ ${2:-} == --history-only ]]; then exit 0; fi
git -C "$root" archive 63f2166 jobs/graphe2/src jobs/graphe1/src | tar -x -C "$work"
export ROLLBACK_G2_SRC="$work/jobs/graphe2/src:$work/jobs/graphe1/src"
unshare --user --map-current-user --net --keep-caps bash -c '
    set -eu
    ip link set lo up
    exec "$@"
' _ "$python" "$root/db/tests/migrated_journey.py" "$work/rollback"
