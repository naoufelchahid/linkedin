"""Ouverture transactionnelle des lots depuis le contrat SQL versionné."""

import os
import tempfile
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class PostgresQueue:
    def __init__(self, data, dsn, candidate):
        self.data = Path(data)
        self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.dsn = dsn
        self.candidate = candidate
        if not candidate:
            raise ValueError("applications_candidate_required")

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def selection(self, db, cycle):
        if not db.execute(
            "SELECT 1 FROM api.cycles_v1 WHERE cycle_id=%s", (cycle,)
        ).fetchone():
            raise ValueError("cycle_not_found")
        return db.execute(
            """SELECT * FROM api.offres_retenues_v1
               WHERE cycle_id=%s AND canonical_url IS NOT NULL AND canonical_url<>''
               ORDER BY incertitude NULLS FIRST, identity""",
            (cycle,),
        ).fetchall()

    def launch(self, data, cycle, mode, offer_keys=()):
        if mode not in {"recipe", "production"}:
            raise ValueError("mode_invalid")
        with self.connect() as db:
            rows = self.selection(db, cycle)
            keys = set(offer_keys)
            if keys and (
                mode != "recipe" or not keys.issubset(r["content"]["key"] for r in rows)
            ):
                raise ValueError("recipe_offers_invalid")
            # Sérialise les reprises du même lot. Les dossiers communs sont
            # toujours acquis dans l’ordre de leur identité pour les autres lots.
            db.execute(
                """INSERT INTO applications.lots(candidate,cycle_id,mode)
                   VALUES(%s,%s,%s) ON CONFLICT DO NOTHING""",
                (self.candidate, cycle, mode),
            )
            lot = db.execute(
                """SELECT id FROM applications.lots
                   WHERE candidate=%s AND cycle_id=%s AND mode=%s""",
                (self.candidate, cycle, mode),
            ).fetchone()["id"]
            ordered = sorted(enumerate(rows), key=lambda entry: entry[1]["identity"])
            for position, row in ordered:
                if keys and row["content"]["key"] not in keys:
                    continue
                db.execute(
                    """INSERT INTO applications.dossiers
                       (id,candidate,identity,mode,cycle_id,version_id,canonical_url,
                        content,cv_sha256,uncertain)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (candidate,identity,mode) DO NOTHING""",
                    (
                        uuid4(),
                        self.candidate,
                        row["identity"],
                        mode,
                        cycle,
                        row["version_id"],
                        row["canonical_url"],
                        Jsonb(row["content"]),
                        row["cv_sha256"],
                        bool(row["incertitude"]),
                    ),
                )
                db.execute(
                    """INSERT INTO applications.lot_dossiers(lot_id,dossier_id,position)
                       SELECT %s,id,%s FROM applications.dossiers
                       WHERE candidate=%s AND identity=%s AND mode=%s
                       ON CONFLICT DO NOTHING""",
                    (lot, position, self.candidate, row["identity"], mode),
                )
            return lot

    def local_pdf(self, digest, pdf):
        if sha256(pdf).hexdigest() != digest:
            raise ValueError("cv_snapshot_integrity")
        directory = self.data / "documents"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / (digest + ".pdf")
        if path.is_file() and sha256(path.read_bytes()).hexdigest() == digest:
            return path
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
            output.write(pdf)
        os.replace(output.name, path)
        return path

    def dossier_letter(self, dossier, source=None):
        """La première lettre enregistrée reste la pièce du dossier après reprise."""
        with self.connect() as db:
            if source is not None:
                db.execute(
                    """INSERT INTO documents.dossier_letters(dossier_id,pdf)
                       SELECT id,%s FROM applications.dossiers
                       WHERE id=%s AND candidate=%s ON CONFLICT DO NOTHING""",
                    (Path(source).read_bytes(), dossier, self.candidate),
                )
            row = db.execute(
                """SELECT l.sha256,l.pdf FROM documents.dossier_letters l
                   JOIN applications.dossiers d ON d.id=l.dossier_id
                   WHERE d.id=%s AND d.candidate=%s""",
                (dossier, self.candidate),
            ).fetchone()
            if row:
                return str(self.local_pdf(row["sha256"], row["pdf"]))
            if source is not None:
                raise ValueError("dossier_letter_unknown")
            return None

    def dossier_document(self, dossier, piece):
        if piece == "letter":
            path = self.dossier_letter(dossier)
            return Path(path) if path else None
        if piece != "cv":
            raise ValueError("unknown_document")
        with self.connect() as db:
            row = db.execute(
                """SELECT cv.sha256,cv.pdf FROM applications.dossiers d
                   JOIN documents.cv_versions cv ON cv.sha256=d.cv_sha256
                   WHERE d.id=%s AND d.candidate=%s""",
                (dossier, self.candidate),
            ).fetchone()
            return self.local_pdf(row["sha256"], row["pdf"]) if row else None

    def items(self):
        with self.connect() as db:
            rows = db.execute(
                """SELECT d.*, cv.pdf, cv.markdown FROM applications.dossiers d
                   JOIN documents.cv_versions cv ON cv.sha256=d.cv_sha256
                   JOIN LATERAL (SELECT lot_id, position FROM applications.lot_dossiers
                     WHERE dossier_id=d.id ORDER BY lot_id,position LIMIT 1) first_lot ON true
                   WHERE d.candidate=%s ORDER BY first_lot.lot_id,first_lot.position,d.id""",
                (self.candidate,),
            )
            return [
                {
                    "dossier": str(row["id"]),
                    "mode": row["mode"],
                    "version": row["version_id"],
                    "offer": {**row["content"], "url": row["canonical_url"]},
                    "cv": str(self.local_pdf(row["cv_sha256"], row["pdf"])),
                    "cv_hash": row["cv_sha256"],
                    "cv_text": row["markdown"],
                    "uncertain": row["uncertain"],
                }
                for row in rows
            ]
