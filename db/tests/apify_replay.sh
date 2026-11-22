#!/usr/bin/env bash
# Recette autonome. PostgreSQL, ses données et le port local sont éphémères.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
python="$root/jobs/graphe1/.venv/bin/python"
export POSTGRES_PASSWORD
POSTGRES_PASSWORD=$(openssl rand -hex 24)
container=$(docker run -d --rm -e POSTGRES_PASSWORD -p 127.0.0.1::5432 postgres:17)
work=$(mktemp -d)
trap 'docker rm -fv "$container" >/dev/null; rm -rf "$work"' EXIT
export PGHOST=127.0.0.1 PGUSER=postgres PGDATABASE=postgres PGPASSWORD="$POSTGRES_PASSWORD"
export PGPORT
PGPORT=$(docker port "$container" 5432/tcp | cut -d: -f2)
unset PGSERVICE PGOPTIONS PGHOSTADDR
for _ in {1..60}; do
    if pg_isready -q; then break; fi
    sleep 1
done
for _ in 1 2; do
    psql -Xqf "$root/db/bootstrap.sql" >/dev/null
    psql -Xqf "$root/db/migrate.sql" >/dev/null
done

export PGOPTIONS='-c role=linkedin_discovery'
cat > "$work/dataset.json" <<'JSON'
[{"id":"42","title":"Analyste","contractType":"CDI","company":{"name":"Atelier"},"location":"Rabat","url":"https://www.linkedin.com/jobs/view/test-42/?trk=abc","descriptionHtml":"<p>Analyser les données.</p>","nouveau":{"tags":["a","b"],"visible":false,"mesure":0.12345678901234567890123}},{"inexploitable":true}]
JSON
replay() {
    "$python" -m linkedin_discovery.postgres_import --cycle "$1" --profile test "$2"
}
test "$(replay A "$work/dataset.json")" = '{"occurrences_inserted": 2}'
test "$(replay A "$work/dataset.json")" = '{"occurrences_inserted": 0}'
test "$(replay B "$work/dataset.json")" = '{"occurrences_inserted": 2}'

"$python" - "$work/dataset.json" <<'PY'
import json
import sys

import psycopg

with open(sys.argv[1], encoding="utf-8") as stream:
    raw, unusable = json.load(stream)
with psycopg.connect() as db:
    row = db.execute("""
        SELECT title, contract_type, company, location, canonical_url, missions, raw,
               pg_typeof(raw)::text
        FROM discovery.occurrences WHERE cycle_id='A' AND version_id IS NOT NULL
    """).fetchone()
    assert row == ("Analyste", "CDI", "Atelier", "Rabat", "https://www.linkedin.com/jobs/view/42",
                   "Analyser les données.", raw, "jsonb"), row
    assert db.execute("""SELECT raw, error FROM discovery.occurrences
                         WHERE cycle_id='A' AND version_id IS NULL""").fetchone() == (
        unusable, "announcement_unusable")
    assert db.execute("""SELECT raw #>> '{nouveau,mesure}' FROM discovery.occurrences
                         WHERE cycle_id='A' AND version_id IS NOT NULL""").fetchone() == (
        "0.12345678901234567890123",)
    assert db.execute("SELECT count(*) FROM discovery.versions").fetchone() == (1,)
    assert db.execute("SELECT count(*) FROM discovery.occurrences").fetchone() == (4,)
    assert db.execute("""SELECT has_schema_privilege(current_user, 'discovery', 'CREATE'),
                                has_table_privilege(current_user, 'discovery.occurrences', 'DELETE')
                      """).fetchone() == (False, False)
PY
echo '[{"id":"rollback"},"invalide"]' > "$work/invalid.json"
if replay C "$work/invalid.json" > /dev/null 2>&1; then exit 1; fi
test "$(psql -XAtqc "SELECT count(*) FROM discovery.occurrences WHERE cycle_id='C'")" = 0
test "$(psql -XAtqc 'SELECT count(*) FROM discovery.versions')" = 1
echo 'Rejeu PostgreSQL, transactions et droits vérifiés.'

TEST_CV_POSTGRES_DSN="dbname=$PGDATABASE" "$python" -m pytest -q \
    "$root/jobs/graphe1/tests/test_discovery.py::test_two_cycle_documents_postgres" \
    "$root/jobs/graphe1/tests/test_discovery.py::test_postgres_qualification_review_replay"
