#!/usr/bin/env bash
# Recette de lecture sur PostgreSQL jetable et viewport mobile Chrome.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
python=${PYTHON:-"$root/jobs/graphe1/.venv/bin/python"}
work=$(mktemp -d)
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(openssl rand -hex 24)
pg=$(docker run -d --rm -e POSTGRES_PASSWORD -p 127.0.0.1::5432 postgres:17)
trap 'docker rm -fv "$pg" >/dev/null; rm -rf "$work"' EXIT
export PGHOST=127.0.0.1 PGUSER=postgres PGDATABASE=postgres PGPASSWORD="$POSTGRES_PASSWORD"
export PGPORT
PGPORT=$(docker port "$pg" 5432/tcp | cut -d: -f2)
unset PGSERVICE PGOPTIONS PGHOSTADDR
for _ in {1..60}; do pg_isready -q && break; sleep 1; done
psql -Xqf "$root/db/bootstrap.sql" >/dev/null
psql -Xqf "$root/db/migrate.sql" >/dev/null
PYTHONPATH="$root/jobs/graphe1/src" "$python" "$root/db/tests/web_offers.py" "$work"
"${CHROME:-google-chrome}" --headless --no-sandbox --disable-gpu --disable-background-networking \
    --disable-dev-shm-usage --user-data-dir="$work/profile" --window-size=390,844 \
    --dump-dom "file://$work/mobile.html" > "$work/dom" 2>"$work/chrome.log"
rg -q 'data-mobile="ok"' "$work/dom"
PYTHONPATH="$root/jobs/graphe1/src" "$python" "$root/db/tests/web_offer_detail.py" "$work"
"${CHROME:-google-chrome}" --headless --no-sandbox --disable-gpu --disable-background-networking \
    --disable-dev-shm-usage --user-data-dir="$work/profile" --window-size=390,844 \
    --dump-dom "file://$work/detail.html" > "$work/detail-dom" 2>"$work/detail-chrome.log"
rg -q 'data-detail="ok"' "$work/detail-dom"
echo 'Fiche, chronologie, reçu et retour à la page filtrée vérifiés.'
echo 'Liste web vérifiée sur PostgreSQL, desktop et mobile.'
