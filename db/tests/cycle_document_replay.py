"""Même PDF, deux textes historiques, depuis la migration de la version précédente."""

import hashlib
import subprocess
import tempfile
from pathlib import Path

import psycopg
from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_discovery.config import Config
from linkedin_discovery.documents import cycle_cv, freeze_cv
from linkedin_discovery.workflow import Pilot

PDF = b"%PDF fixture commune"
SHA = hashlib.sha256(PDF).hexdigest()
TEXTS = ("Texte historique A\n", "# Nouvelle lecture\n\nTexte B")
G1 = "options='-c role=linkedin_discovery'"
G2 = "options='-c role=linkedin_applications'"


def seed():
    with psycopg.connect() as db:
        assert db.execute("SELECT current_database()").fetchone() == ("rehearsal_cv",)
        db.execute(
            "INSERT INTO documents.cv_versions VALUES(%s,%s,'lecture commune','fixture',DEFAULT)",
            (SHA, PDF),
        )
        db.execute("""INSERT INTO discovery.versions(id,offer_key,content,canonical_url)
            VALUES('v','k','{"key":"k","title":"Poste","url":"https://example.invalid/a"}','https://example.invalid/a')""")
        db.execute(
            """INSERT INTO discovery.qualifications VALUES('q','v',%s,'p','done',
            '{"verdict":"retenir","incertitude":false}','')""",
            (SHA,),
        )
        for index, text in enumerate(TEXTS):
            cycle = str(index)
            db.execute(
                "INSERT INTO discovery.cycles VALUES(%s,'2026-01-01',%s,%s,'p','p','{}','done')",
                (cycle, SHA, text),
            )
            if not index:
                db.execute("INSERT INTO discovery.cycle_cv VALUES(%s,%s)", (cycle, SHA))
            db.execute("INSERT INTO discovery.cycle_items VALUES(%s,'v','q')", (cycle,))
            db.execute(
                """INSERT INTO discovery.reports VALUES(%s,%s,'2026-01-01',%s,'','')""",
                (
                    "report-" + cycle,
                    cycle,
                    '{"cycle_id":"' + cycle + '","selected":[]}',
                ),
            )


def check():
    seed()
    migrate = Path(__file__).resolve().parents[1] / "migrate.sql"
    subprocess.run(
        ["psql", "-Xqf", str(migrate)], stdout=subprocess.DEVNULL, check=True
    )
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        pilot = Pilot(Config(root=root, postgres_dsn=G1))
        try:
            first = PostgresQueue(root / "first", G2, "first")
            for index, expected in enumerate(TEXTS):
                cycle = str(index)
                assert cycle_cv(G1, cycle) == (PDF, expected)
                replay = pilot.replay("report-" + cycle)
                assert pilot.store.cycle(replay)["cv_text"] == expected
                assert cycle_cv(G1, replay) == (PDF, expected)
                first.launch(None, cycle, "recipe")
                (old,) = first.items()
                assert (Path(old["cv"]).read_bytes(), old["cv_text"]) == (PDF, TEXTS[0])
            fresh = PostgresQueue(root / "fresh", G2, "fresh")
            fresh.launch(None, "1", "recipe")
            (new,) = fresh.items()
            assert (Path(new["cv"]).read_bytes(), new["cv_text"]) == (PDF, TEXTS[1])
            try:
                freeze_cv(G1, "0", PDF, "Autre texte", "fixture")
            except ValueError as error:
                assert str(error) == "cycle_cv_changed"
            else:
                raise AssertionError("Modification documentaire acceptée")
            assert cycle_cv(G1, "0") == (PDF, TEXTS[0])
        finally:
            pilot.store.close()
    print("Migration des deux liaisons, relecture G1/G2 et immutabilité vérifiées.")


if __name__ == "__main__":
    check()
