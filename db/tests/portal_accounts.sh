#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
: "${PLAYWRIGHT:?Module Node Playwright requis}" "${CHROME:?Exécutable Chrome requis}"
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(openssl rand -hex 24)
pg=$(docker run -d --rm -e POSTGRES_PASSWORD -p 127.0.0.1::5432 postgres:17)
trap 'docker rm -fv "$pg" >/dev/null' EXIT
export PGHOST=127.0.0.1 PGDATABASE=postgres PGPASSWORD="$POSTGRES_PASSWORD" PGUSER=postgres
export PGPORT
PGPORT=$(docker port "$pg" 5432/tcp | cut -d: -f2)
unset PGSERVICE PGOPTIONS PGHOSTADDR
for _ in {1..60}; do pg_isready -q && break; sleep 1; done
docker cp "$root/db" "$pg:/recette"
"${PYTHON:-$root/jobs/graphe2/.venv/bin/python}" "$root/jobs/graphe2/tests/recette_comptes/run.py" "$pg" "$PLAYWRIGHT" "$CHROME"
