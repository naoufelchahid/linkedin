#!/usr/bin/env bash
# Ouvre des lots synthétiques dans une base et un réseau Docker éphémères.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
image=$(docker build -q -t linkedin-applications:recette-08 "$root/jobs/graphe2")
network=$(docker network create --internal "lots-recette-$$")
pg=""
cleanup() {
    if [[ -n "$pg" ]]; then docker rm -fv "$pg" >/dev/null; fi
    docker network rm "$network" >/dev/null
}
trap cleanup EXIT
pg=$(docker run -d --rm --network "$network" --network-alias db \
    -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17)
for _ in {1..60}; do
    if docker exec "$pg" pg_isready -q; then break; fi
    sleep 1
done
docker cp "$root/db/." "$pg:/tmp/migrations"
sql() { docker exec -i "$pg" psql -XqAt -v ON_ERROR_STOP=1 -U postgres "$@"; }
sql -f /tmp/migrations/bootstrap.sql >/dev/null
sql -f /tmp/migrations/migrate.sql >/dev/null
sql <<'SQL'
CREATE ROLE recette LOGIN IN ROLE linkedin_applications;
SQL
publish() {
    sql -v version="$1" <<'SQL'
INSERT INTO documents.cv_versions (sha256,pdf,markdown,provenance)
SELECT encode(sha256(pdf),'hex'),pdf,name,'fixture' FROM
(values (:'version',convert_to('%PDF ' || :'version', 'UTF8'))) doc(name,pdf);
INSERT INTO discovery.cycles
SELECT repeat(lower(markdown),32),'now',sha256,markdown,'p','p','{}','done' FROM documents.cv_versions WHERE markdown=:'version';
INSERT INTO discovery.versions(id,offer_key,content,canonical_url)
SELECT markdown,'k',jsonb_build_object('key','k','title',markdown),'https://example.invalid/1' FROM documents.cv_versions WHERE markdown=:'version';
INSERT INTO discovery.qualifications(id,version_id,cv_hash,prompt_hash,status,result)
SELECT markdown,markdown,sha256,'p','done','{"verdict":"retenir","incertitude":false}' FROM documents.cv_versions WHERE markdown=:'version';
INSERT INTO discovery.cycle_items SELECT repeat(lower(markdown),32), markdown,markdown FROM documents.cv_versions WHERE markdown=:'version';
SQL
}
publish A
cli=(docker run --rm --network "$network" -e "APPLICATIONS_POSTGRES_DSN=host=db dbname=postgres user=recette" -e APPLICATIONS_CANDIDATE=test)
launch() { "${cli[@]}" "$image" --state /tmp/etat launch --cycle "$1" --mode "$2" --queue-only; }
a=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
b=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
first=$(launch "$a" recipe)
test "$(launch "$a" recipe)" = "$first"
publish B
launch "$b" recipe >/dev/null
launch "$b" production >/dev/null
test "$(sql -c 'SELECT count(*) FROM applications.lots')" = 3
test "$(sql -c 'SELECT count(*) FROM applications.lot_dossiers')" = 3
test "$(sql -c 'SELECT count(*) FROM applications.dossiers')" = 2
"${cli[@]}" --entrypoint python "$image" -c '
import importlib.util, os
from pathlib import Path
from linkedin_applications.postgres_queue import PostgresQueue
assert importlib.util.find_spec("linkedin_discovery") is None
items = PostgresQueue("/tmp/etat", os.environ["APPLICATIONS_POSTGRES_DSN"], "test").items()
assert len(items) == 2 and items[0]["dossier"] != items[1]["dossier"]
for item, mode, version in zip(items, ["recipe","production"], ["A","B"], strict=True):
    assert item["mode"] == mode and item["version"] == item["cv_text"] == item["offer"]["title"] == version
    assert Path(item["cv"]).read_bytes() == ("%PDF " + version).encode()
'
echo "Trois lots, deux dossiers, versions A et B et CV relus depuis le worker isolé."
"${cli[@]}" --entrypoint python -v "$root/db/tests/dossier_uploads.py:/recette.py:ro" "$image" /recette.py
"${cli[@]}" --entrypoint python -v "$root/db/tests/submission_recovery.py:/recette.py:ro" "$image" /recette.py
"${cli[@]}" --entrypoint python -v "$root/db/tests/attempt_trace.py:/recette.py:ro" "$image" /recette.py
"${cli[@]}" --entrypoint python -v "$root/db/tests/telegram_answers.py:/recette.py:ro" "$image" /recette.py
