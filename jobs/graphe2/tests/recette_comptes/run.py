"""Vérifier deux comptes dans Chrome avant et après restauration PostgreSQL."""

import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import psycopg
from linkedin_applications.accounts import PortalAccounts, confirm_address
from linkedin_applications.codex import ConnectorError
from linkedin_applications.postgres_queue import PostgresQueue


class LocalPortal:
    def __init__(self, process):
        self.process = process

    def command(self, **arguments):
        self.process.stdin.write(json.dumps(arguments) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    async def current_url(self, rpc, tab):
        assert rpc is None and tab == 1
        return self.command(cmd="url")

    async def use(self, rpc, name, args):
        assert name == "page_fillInput"
        return self.command(
            cmd="fill", selector=args["target"]["selector"], value=args["value"]
        )


def main():
    pg, module, chrome = sys.argv[1:]
    root = Path(__file__).resolve().parents[4]
    run = ["docker", "exec", "-i", pg]

    def sql(*args, script=None):
        subprocess.run(
            run
            + ["psql", "-q", "-X", "-v", "ON_ERROR_STOP=1", "-U", "postgres", *args],
            input=script,
            stdout=subprocess.DEVNULL,
            check=True,
        )

    for target in ("bootstrap", "migrate"):
        sql("-f", f"/recette/{target}.sql")
    sql(
        script=b"""\\getenv worker_password POSTGRES_PASSWORD
        CREATE ROLE recette LOGIN PASSWORD :'worker_password' IN ROLE linkedin_applications;
        INSERT INTO documents.cv_versions (sha256,pdf,markdown,provenance)
        VALUES (encode(sha256('%PDF fixture'::bytea),'hex'),'%PDF fixture','cv','fixture');
        INSERT INTO discovery.cycles SELECT repeat('a',32),'now',sha256,'cv','p','p','{}','done' FROM documents.cv_versions;
        INSERT INTO discovery.versions(id,offer_key,content,canonical_url)
        VALUES ('A','A','{"company":"A"}','https://example.invalid/a'),('B','B','{"company":"B"}','https://example.invalid/b');
    """
    )
    ids = [uuid4(), uuid4()]
    with psycopg.connect(user="postgres") as admin:
        for employer, ident in zip("AB", ids, strict=True):
            admin.execute(
                """INSERT INTO applications.dossiers(id,candidate,identity,mode,cycle_id,version_id,canonical_url,content,cv_sha256,uncertain)
                SELECT %s,'fixture',%s,'recipe',c.id,v.id,v.canonical_url,v.content,c.cv_hash,false
                FROM discovery.cycles c,discovery.versions v WHERE v.id=%s""",
                (ident, employer, employer),
            )
    origin = "https://portail.invalid"
    rules = [{"url": origin + "/" + e.lower(), "space": e, "employer": e} for e in "AB"]
    permission = [{"kind": "registration", "scope": origin, "choice": "allow"}]
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp)
        queue = PostgresQueue(home, "dbname=postgres user=recette", "fixture")
        key = home / "key"
        key.write_bytes(base64.b64encode(os.urandom(32)))
        key.chmod(0o600)
        accounts = PortalAccounts(queue, key, rules)
        with subprocess.Popen(
            [
                "node",
                root / "jobs/graphe2/tests/recette_comptes/portal.cjs",
                module,
                chrome,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        ) as process:
            portal = LocalPortal(process)

            def fill(index, allowed):
                return asyncio.run(accounts.fill(portal, None, ids[index], 1, allowed))

            try:
                portal.command(cmd="open", space=0)
                try:
                    fill(0, permission)
                except ConnectorError as exc:
                    assert str(exc) == "portal_account_address_unconfirmed"
                else:
                    raise AssertionError("adresse absente acceptée")
                confirm_address(queue, "recipe", "candidat@example.invalid")
                try:
                    fill(0, [])
                except ConnectorError as exc:
                    assert str(exc) == "portal_account_approval_required"
                else:
                    raise AssertionError("création sans accord")
                for i in range(2):
                    portal.command(cmd="open", space=i)
                    assert fill(i, permission) == "creation_en_cours"
                    assert portal.command(cmd="submit") == "Créé"
                portal.command(cmd="open", space=1)
                try:
                    fill(0, permission)
                except ConnectorError as exc:
                    assert str(exc) == "portal_account_destination_unknown"
                else:
                    raise AssertionError("mauvais espace accepté")
                # Le dump est restitué dans une seconde base du conteneur jetable.
                dump = subprocess.check_output(
                    run + ["pg_dump", "-U", "postgres", "-Fc", "postgres"]
                )
                sql("-c", "CREATE DATABASE restored")
                subprocess.run(
                    run
                    + [
                        "pg_restore",
                        "-U",
                        "postgres",
                        "-d",
                        "restored",
                        "--exit-on-error",
                    ],
                    input=dump,
                    check=True,
                )
                queue = PostgresQueue(
                    home / "reprise", "dbname=restored user=recette", "fixture"
                )
                accounts = PortalAccounts(queue, key, rules)
                for i in range(2):
                    portal.command(cmd="open", space=i)
                    fill(i, [])
                    assert portal.command(cmd="submit") == "Retrouvé"
                key.write_bytes(base64.b64encode(os.urandom(32)))
                portal.command(cmd="open", space=0)
                try:
                    fill(0, [])
                except ConnectorError as exc:
                    assert str(exc) == "portal_account_key_mismatch"
                else:
                    raise AssertionError("mauvaise clé acceptée")
                with queue.connect() as db:
                    assert (
                        db.execute(
                            "SELECT count(*) AS n FROM applications.dossier_portal_accounts"
                        ).fetchone()["n"]
                        == 2
                    )
            finally:
                process.stdin.close()
        assert process.returncode == 0
    print(
        "Deux comptes Chrome créés puis retrouvés après restauration. Isolation des espaces, adresse, accord et clé vérifiés."
    )


if __name__ == "__main__":
    main()
