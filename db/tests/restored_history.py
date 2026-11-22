"""Migration privée d'une copie #1 vers la base isolée de répétition."""

import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import ormsgpack
import psycopg
from linkedin_discovery.documents import freeze_cv_in
from linkedin_discovery.model import offer_url, plain
from linkedin_discovery.retained import retained_rows
from psycopg import sql
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from restore_baseline import check_state, manifest, read_db


def require(condition, label):
    if not condition:
        raise ValueError(label)


def discovery(db, pg, directory):
    db.row_factory = sqlite3.Row
    select = db.execute
    for row in select("SELECT id,cv_hash FROM cycles ORDER BY created_at"):
        pdf = (directory / "snapshots" / (row["cv_hash"] + ".pdf")).read_bytes()
        require(sha256(pdf).hexdigest() == row["cv_hash"], "CV original")
        freeze_cv_in(pg, row["id"], pdf, None, "Copie restaurée du graphe 1")
    for row in select("SELECT * FROM versions"):
        content = json.loads(row["content"])
        pg.execute(
            """INSERT INTO discovery.versions(id,offer_key,content,canonical_url,created_at)
               VALUES (%s,%s,%s::jsonb,%s,%s)""",
            (
                row["id"],
                row["offer_key"],
                row["content"],
                offer_url(content.get("url")) or None,
                row["created_at"],
            ),
        )
    for row in select("""SELECT o.*,v.content FROM occurrences o
                         LEFT JOIN versions v ON v.id=o.version_id"""):
        raw = json.loads(row["raw"])
        content = json.loads(row["content"] or "{}")
        contract = (
            raw.get("contractType") or raw.get("employmentType") or raw.get("jobType")
        )
        pg.execute(
            """INSERT INTO discovery.occurrences
               (cycle_id,profile,raw_hash,raw,version_id,error,observed_at,title,contract_type,
                company,location,canonical_url,missions)
               VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["cycle_id"],
                row["profile"],
                row["raw_hash"],
                row["raw"],
                row["version_id"],
                None if row["version_id"] else row["error"],
                row["observed_at"],
                content.get("title"),
                plain(contract) or None,
                content.get("company"),
                content.get("location"),
                offer_url(content.get("url")) or None,
                content.get("description"),
            ),
        )
    for table in (
        "cycles",
        "runs",
        "qualifications",
        "attempts",
        "attempt_responses",
        "cycle_items",
        "reports",
        "review_items",
        "reviews",
        "events",
    ):
        rows = select(f"SELECT * FROM {table}")
        names = [c[0] for c in rows.description]
        command = sql.SQL(
            "INSERT INTO discovery.{} ({}) OVERRIDING SYSTEM VALUE VALUES ({})"
        ).format(
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, names)),
            sql.SQL(",").join([sql.Placeholder()] * len(names)),
        )
        pg.cursor().executemany(command, rows)
        if table in ("attempts", "reviews", "events"):
            pg.execute(
                sql.SQL("""SELECT setval(pg_get_serial_sequence(%s,'id'),
                 coalesce(max(id),1),max(id) IS NOT NULL) FROM discovery.{}""").format(
                    sql.Identifier(table)
                ),
                ("discovery." + table,),
            )
    for report in (directory / "validations").glob("*.json"):
        data = json.loads(report.read_bytes())
        pg.execute(
            "INSERT INTO discovery.pilot_validations VALUES(%s,%s)",
            (data["report_id"], data["recorded_at"]),
        )
    for table in (
        "cycles",
        "versions",
        "occurrences",
        "runs",
        "qualifications",
        "attempts",
        "attempt_responses",
        "cycle_items",
        "reports",
        "review_items",
        "reviews",
        "events",
    ):
        total = select(f"SELECT count(*) FROM {table}").fetchone()[0]
        require(
            pg.execute(
                sql.SQL("SELECT count(*) FROM discovery.{}").format(
                    sql.Identifier(table)
                )
            ).fetchone()[0]
            == total,
            table,
        )
    for (cycle,) in select("SELECT id FROM cycles").fetchall():
        old = {(r["identity"], r["id"]) for r in retained_rows(db, cycle)}
        new = set(
            pg.execute(
                "SELECT identity,version_id FROM api.offres_retenues_v1 WHERE cycle_id=%s",
                (cycle,),
            )
        )
        require(old == new, "sélection du cycle")


def checkpoint_facts(db):
    facts = {}
    states = {}
    letters = {}
    for thread, kind, blob in db.execute(
        """SELECT thread_id,type,checkpoint FROM checkpoints
           WHERE checkpoint_ns='' ORDER BY checkpoint_id"""
    ):
        require(kind == "msgpack", "encodage du checkpoint")
        # Ne pas exécuter d'extension de désérialisation issue d'une sauvegarde.
        state = ormsgpack.unpackb(blob, ext_hook=lambda *args: None)["channel_values"]
        if "mode" in state:
            states[thread] = (state["mode"], state.get("status", "queued"))
            if state.get("letter"):
                letters[thread, state["mode"]] = state["letter"]
        if question := state.get("question"):
            facts["question", json.dumps([thread, question["id"]])] = question
        for index, answer in enumerate(state.get("answers", [])):
            encoded = json.dumps(answer, sort_keys=True)
            key = json.dumps([thread, index, sha256(encoded.encode()).hexdigest()])
            facts["answer", key] = answer
        for field in ("submission", "mail"):
            if op := state.get(field):
                key = json.dumps([thread, field, op["id"]])
                facts["attempt", key] = op
                proof = op.get("receipt") or (
                    state.get("evidence") if field == "submission" else None
                )
                if proof:
                    facts["receipt", key] = proof
    return states, facts, letters


def applications(directory, pg, reference):
    with closing(read_db(directory / "checkpoints.sqlite3", snapshot=True)) as db:
        states, facts, letters = checkpoint_facts(db)
    for key, (mode, status) in states.items():
        facts["thread", key] = {"mode": mode, "status": status}
    memory = directory / "reponses.md"
    if memory.exists():
        for index, line in enumerate(memory.read_text().splitlines()):
            if line.startswith("- "):
                facts["memory", str(index)] = json.loads(line[2:])
    ids = {}
    with closing(read_db(directory / "queue.sqlite3", snapshot=True)) as db:
        for old_lot, cycle, mode in db.execute(
            "SELECT id,cycle,mode FROM lots ORDER BY id"
        ):
            lot = pg.execute(
                """INSERT INTO applications.lots(candidate,cycle_id,mode)
                          VALUES('restored',%s,%s) RETURNING id""",
                (cycle, mode),
            ).fetchone()[0]
            for thread, position, payload in db.execute(
                "SELECT dossier,position,payload FROM items WHERE lot=? ORDER BY position",
                (old_lot,),
            ):
                item = json.loads(payload)
                identity = offer_url(item["offer"]["url"])
                require(
                    identity and sha256(identity.encode()).hexdigest() == thread,
                    "identité historique",
                )
                key = (thread, mode)
                if key not in ids:
                    dossier = ids[key] = uuid4()
                    pg.execute(
                        """INSERT INTO applications.dossiers
                      (id,candidate,identity,mode,cycle_id,version_id,canonical_url,content,cv_sha256,uncertain)
                      VALUES(%s,'restored',%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            dossier,
                            identity,
                            mode,
                            cycle,
                            item["version"],
                            identity,
                            Jsonb(item["offer"]),
                            item["cv_hash"],
                            item["uncertain"],
                        ),
                    )
                    old_mode, status = states.get(thread, (None, "queued"))
                    pg.execute(
                        "INSERT INTO applications.legacy_holds VALUES (%s,%s,%s,%s)",
                        (
                            dossier,
                            thread,
                            old_mode,
                            status if mode == old_mode else "sans_checkpoint_du_mode",
                        ),
                    )
                pg.execute(
                    "INSERT INTO applications.lot_dossiers VALUES (%s,%s,%s)",
                    (lot, ids[key], position),
                )
        expected_links = db.execute("SELECT count(*) FROM items").fetchone()[0]
    for (thread, mode), name in letters.items():
        parts = Path(name).parts
        file = directory.joinpath(*parts[parts.index("documents") :])
        pg.execute(
            "INSERT INTO documents.dossier_letters(dossier_id,pdf) VALUES(%s,%s)",
            (ids[thread, mode], file.read_bytes()),
        )
    pg.cursor().executemany(
        "INSERT INTO applications.legacy_history VALUES(%s,%s,%s)",
        ((kind, k, Jsonb(value)) for (kind, k), value in facts.items()),
    )
    actual = {
        (kind, key): payload
        for kind, key, payload in pg.execute(
            "SELECT * FROM applications.legacy_history"
        )
    }
    require(actual == facts, "historique détaillé")
    counts = Counter(kind for kind, key in actual)
    for kind, name in (
        ("attempt", "application_attempts"),
        ("receipt", "application_receipts"),
        ("answer", "dossier_answers"),
        ("memory", "saved_answers"),
    ):
        require(counts[kind] == reference[name], kind)
    require(
        dict(Counter(status for _, status in states.values()))
        == reference["dossier_status"],
        "états ouverts",
    )
    require(
        pg.execute("SELECT count(*) FROM applications.lots").fetchone()[0]
        == reference["lots"],
        "lots",
    )
    require(
        pg.execute("SELECT count(*) FROM applications.lot_dossiers").fetchone()[0]
        == expected_links,
        "liens",
    )
    return counts


def migrate(bundle, rollback):
    expected = json.loads((bundle / "sha256.json").read_bytes())
    restored = bundle / "restored"
    require(
        manifest(restored) == expected == manifest(bundle / "reference"),
        "empreintes source",
    )
    reference = json.loads((bundle / "counts.json").read_text())
    require(
        {**check_state(restored), "verified_files": len(expected)} == reference,
        "référence",
    )
    with psycopg.connect() as pg:
        require(
            pg.execute("SELECT current_database()").fetchone() == ("rehearsal_21",),
            "base de répétition",
        )
        with closing(
            read_db(restored / "discovery/discovery.sqlite3", snapshot=True)
        ) as legacy:
            discovery(legacy, pg, restored / "discovery")
        counts = applications(restored / "applications", pg, reference)
        for rel, h in expected.items():
            pg.execute(
                "INSERT INTO applications.legacy_files VALUES(%s,%s,%s)",
                (rel, (restored / rel).read_bytes(), h),
            )
    # Reconstruction sur un nouvel emplacement à partir de la seule copie SQL.
    rollback.mkdir(mode=0o700)
    with psycopg.connect() as pg:
        for name, data in pg.execute(
            "SELECT relative_path,content FROM applications.legacy_files"
        ):
            target = (rollback / name).resolve()
            require(target.is_relative_to(rollback.resolve()), "chemin de restauration")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(data)
    require(
        manifest(rollback) == expected and manifest(restored) == expected,
        "retour arrière",
    )
    require(
        {**check_state(rollback), "verified_files": len(expected)} == reference,
        "état restauré",
    )
    print(
        "Réconciliation des volumes, états et contenus réussie.",
        dict(sorted(counts.items())),
    )
    print(f"Retour arrière : {len(expected)} fichiers identiques à la référence.")


if __name__ == "__main__":
    try:
        migrate(Path(sys.argv[1]), Path(sys.argv[2]))
    except psycopg.Error as exc:
        sys.exit(f"Migration interrompue (PostgreSQL {exc.sqlstate}).")
