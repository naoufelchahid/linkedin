"""Version documentaire immuable, adressée par l'empreinte du PDF original."""

import psycopg

from .adapters.pdf import extract_text
from .model import digest


def freeze_cv(dsn, cycle_id, pdf, text, provenance):
    with psycopg.connect(dsn) as db:
        return freeze_cv_in(db, cycle_id, pdf, text, provenance)


def freeze_cv_in(db, cycle_id, pdf, text, provenance):
    from psycopg.rows import tuple_row

    sha256 = digest(pdf)
    with db.cursor(row_factory=tuple_row) as cursor:
        # Sérialise l'extraction si deux cycles publient le même PDF simultanément.
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (sha256,))
        row = cursor.execute(
            "SELECT markdown FROM documents.cv_versions WHERE sha256 = %s", (sha256,)
        ).fetchone()
        if row:
            markdown = row[0]
        else:
            # Les blocs de texte extraits dans l'ordre de lecture sont des paragraphes Markdown.
            body = text if text is not None else extract_text(pdf)
            if not body.strip():
                raise ValueError("cv_text_unreadable")
            markdown = "# Curriculum vitæ\n\n" + body.replace("\f", "\n\n").strip()
            cursor.execute(
                """INSERT INTO documents.cv_versions (sha256, pdf, markdown, provenance)
                   VALUES (%s, %s, %s, %s)""",
                (sha256, pdf, markdown, provenance),
            )
        cursor.execute(
            """INSERT INTO discovery.cycle_cv (cycle_id, cv_sha256) VALUES (%s, %s)
               ON CONFLICT (cycle_id) DO NOTHING""",
            (cycle_id, sha256),
        )
        bound = cursor.execute(
            "SELECT cv_sha256 FROM discovery.cycle_cv WHERE cycle_id = %s", (cycle_id,)
        ).fetchone()
        if bound != (sha256,):
            raise ValueError("cycle_cv_changed")
    return markdown


def cycle_cv(dsn, cycle_id):
    """Résout le PDF original et le Markdown du cycle, indépendamment des chemins locaux."""
    with psycopg.connect(dsn) as db:
        return db.execute(
            """SELECT v.pdf, v.markdown FROM discovery.cycle_cv c
               JOIN documents.cv_versions v ON v.sha256 = c.cv_sha256
               WHERE c.cycle_id = %s""",
            (cycle_id,),
        ).fetchone()
