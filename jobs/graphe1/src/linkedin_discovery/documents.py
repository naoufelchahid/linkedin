"""Version documentaire immuable, adressée par l'empreinte du PDF original."""

import psycopg

from .adapters.pdf import extract_text
from .model import digest


def _markdown(body):
    if not body.strip():
        raise ValueError("cv_text_unreadable")
    return "# Curriculum vitæ\n\n" + body.replace("\f", "\n\n").strip()


def freeze_cv(dsn, cycle_id, pdf, text, provenance):
    with psycopg.connect(dsn) as db:
        return freeze_cv_in(db, cycle_id, pdf, text, provenance)


def freeze_cv_in(db, cycle_id, pdf, text, provenance, *, text_is_frozen=False):
    from psycopg.rows import tuple_row

    supplied = _markdown(text) if text is not None and not text_is_frozen else None
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
            markdown = supplied or _markdown(extract_text(pdf))
            cursor.execute(
                """INSERT INTO documents.cv_versions (sha256, pdf, markdown, provenance)
                   VALUES (%s, %s, %s, %s)""",
                (sha256, pdf, markdown, provenance),
            )
        frozen = text if text_is_frozen else supplied or markdown
        cursor.execute(
            """INSERT INTO discovery.cycle_cv (cycle_id, cv_sha256, frozen_text) VALUES (%s, %s, %s)
               ON CONFLICT (cycle_id) DO NOTHING""",
            (cycle_id, sha256, frozen),
        )
        bound = cursor.execute(
            "SELECT sha256,markdown FROM api.cycle_documents_v1 WHERE cycle_id = %s", (cycle_id,)
        ).fetchone()
        if bound[0] != sha256 or (text is not None and bound[1] != frozen):
            raise ValueError("cycle_cv_changed")
    return bound[1]


def cycle_cv(dsn, cycle_id):
    """Résout le PDF original et le Markdown du cycle, indépendamment des chemins locaux."""
    with psycopg.connect(dsn) as db:
        return db.execute(
            "SELECT pdf,markdown FROM api.cycle_documents_v1 WHERE cycle_id=%s",
            (cycle_id,),
        ).fetchone()
