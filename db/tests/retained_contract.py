"""Comparer le contrat SQL au lecteur SQLite dans la transaction de recette."""

import argparse
import json
import sqlite3
from pathlib import Path

import psycopg
from linkedin_discovery.model import offer_url
from linkedin_discovery.retained import retained_rows


def synthetic():
    db = sqlite3.connect(":memory:")
    schema = (
        Path(__file__).resolve().parents[2]
        / "jobs/graphe1/src/linkedin_discovery/resources/schema.sql"
    )
    db.executescript(schema.read_text())
    for cycle in ("c1", "c2", "empty"):
        db.execute(
            "INSERT INTO cycles VALUES(?, '2026-01-01', ?, '', '', '', '', 'done')",
            (cycle, cycle),
        )
    for version, identity, date, verdict, uncertain in [
        ("a", "same", 1, "retenir", False),
        ("b", "same", 2, "écarter", False),
        ("c", "reviewed", 1, "écarter", True),
        ("d", "unknown", 1, None, None),
        ("e", "", 1, "retenir", True),
    ]:
        content = json.dumps(
            {
                "url": "https://example.invalid/" + identity if identity else "",
                "title": version,
            }
        )
        db.execute(
            "INSERT INTO versions VALUES(?,?,?,?,?)",
            (version, version, version, content, f"2026-01-0{date}"),
        )
        result = (
            json.dumps({"verdict": verdict, "incertitude": uncertain})
            if verdict
            else None
        )
        db.execute(
            "INSERT INTO qualifications VALUES(?,?, '', '', ?, ?, '')",
            (version, version, "done" if verdict else "technical_error", result),
        )
        db.execute("INSERT INTO cycle_items VALUES('c1',?,?)", (version, version))
    db.execute("INSERT INTO cycle_items VALUES('c2','a','a')")
    db.execute("INSERT INTO reports VALUES('report','c1','','','','')")
    db.execute("INSERT INTO review_items VALUES('report',1,'c','c')")
    for verdict in ("écarter", "retenir"):
        db.execute(
            "INSERT INTO reviews(report_id,number,version_id,verdict,created_at) VALUES('report',1,'c',?,'2026-01-01')",
            (verdict,),
        )
    return db


def reconcile(db):
    db.row_factory = sqlite3.Row
    cycles = [r[0] for r in db.execute("SELECT id FROM cycles ORDER BY id")]
    # Seuls les champs contribuant au contrat entrent dans la base jetable.
    with (
        psycopg.connect() as pg,
        pg.transaction(force_rollback=True),
        pg.cursor() as cur,
    ):
        cur.execute("SET LOCAL ROLE linkedin_migrator")
        cur.executemany(
            """INSERT INTO discovery.cycles VALUES(%s,%s,%s,'','','','','done')""",
            db.execute("SELECT id,created_at,cv_hash FROM cycles"),
        )
        cur.executemany(
            """INSERT INTO discovery.versions(id,offer_key,content,canonical_url,created_at)
                           VALUES(%s,%s,%s::jsonb,%s,%s)""",
            (
                (
                    r["id"],
                    r["offer_key"],
                    r["content"],
                    offer_url(json.loads(r["content"]).get("url")) or None,
                    r["created_at"],
                )
                for r in db.execute("SELECT * FROM versions")
            ),
        )
        cur.executemany(
            """INSERT INTO discovery.qualifications(id,version_id,cv_hash,prompt_hash,status,result)
                           VALUES(%s,%s,%s,%s,%s,%s)""",
            db.execute(
                "SELECT id,version_id,cv_hash,prompt_hash,status,result FROM qualifications"
            ),
        )
        cur.executemany(
            "INSERT INTO discovery.cycle_items VALUES(%s,%s,%s)",
            db.execute("SELECT cycle_id,version_id,qualification_id FROM cycle_items"),
        )
        cur.executemany(
            "INSERT INTO discovery.reports VALUES(%s,%s,'','','','')",
            db.execute("SELECT id,cycle_id FROM reports"),
        )
        cur.executemany(
            "INSERT INTO discovery.review_items VALUES(%s,%s,%s,%s)",
            db.execute(
                "SELECT report_id,number,version_id,qualification_id FROM review_items"
            ),
        )
        cur.executemany(
            """INSERT INTO discovery.reviews(report_id,number,version_id,verdict,created_at)
                           VALUES(%s,%s,%s,%s,%s)""",
            db.execute(
                "SELECT report_id,number,version_id,verdict,created_at FROM reviews ORDER BY id"
            ),
        )
        cur.execute("SET LOCAL ROLE linkedin_selection")
        cur.execute("SELECT has_schema_privilege(current_user,'discovery','USAGE')")
        assert cur.fetchone() == (False,)
        for index, cycle in enumerate(cycles, 1):
            expected = {}
            for row in retained_rows(db, cycle):
                content = json.loads(row["content"])
                expected[row["identity"]] = (
                    row["id"],
                    offer_url(content.get("url")) or None,
                    content,
                    row["verdict"],
                    json.loads(row["result"] or "{}").get("incertitude"),
                    row["cv_hash"],
                )
            cur.execute(
                """SELECT identity,version_id,canonical_url,content,verdict,incertitude,cv_sha256
                           FROM api.offres_retenues_v1 WHERE cycle_id=%s""",
                (cycle,),
            )
            rows = cur.fetchall()
            actual = {identity: tuple(values) for identity, *values in rows}
            if actual != expected or len(actual) != len(rows):
                raise RuntimeError(f"Écart sur le cycle de recette {index}")
            print(f"Cycle {index} : {len(rows)} offres retenues, aucun écart.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("restored_sqlite", type=Path, nargs="?")
    args = parser.parse_args()
    source = (
        sqlite3.connect(
            args.restored_sqlite.resolve(strict=True).as_uri() + "?mode=ro&immutable=1",
            uri=True,
        )
        if args.restored_sqlite
        else synthetic()
    )
    try:
        reconcile(source)
    except psycopg.Error as exc:
        raise SystemExit(f"Erreur PostgreSQL de recette ({exc.sqlstate})") from None
    finally:
        source.close()
