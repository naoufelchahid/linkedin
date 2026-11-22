"""Version documentaire immuable, adressée par l'empreinte du PDF original."""

import psycopg

from .adapters.pdf import extract_text
from .model import digest


def freeze_cv(dsn, cycle_id, pdf, text, provenance):
    sha256 = digest(pdf)
    with psycopg.connect(dsn) as db:
        # Sérialise l'extraction si deux cycles publient le même PDF simultanément.
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (sha256,))
        row = db.execute(
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
            db.execute(
                """INSERT INTO documents.cv_versions (sha256, pdf, markdown, provenance)
                   VALUES (%s, %s, %s, %s)""",
                (sha256, pdf, markdown, provenance),
            )
        db.execute(
            """INSERT INTO discovery.cycle_cv (cycle_id, cv_sha256) VALUES (%s, %s)
               ON CONFLICT (cycle_id) DO NOTHING""",
            (cycle_id, sha256),
        )
        bound = db.execute(
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
