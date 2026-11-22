"""Version présentée au candidat et tentative SMTP unique par dépôt confirmé."""

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from psycopg.types.json import Jsonb


def manifest(draft):
    return {
        **draft,
        "attachments": [
            {
                "name": Path(p).name,
                "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest(),
            }
            for p in draft["attachments"]
        ],
    }


def version(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@contextmanager
def frozen_draft(draft):
    """Le connecteur lit les mêmes octets que le dernier contrôle de version."""
    with TemporaryDirectory() as tmp:
        paths = []
        for index, source in enumerate(map(Path, draft["attachments"])):
            directory = Path(tmp) / str(index)
            directory.mkdir()
            path = directory / source.name
            path.write_bytes(source.read_bytes())
            paths.append(str(path))
        yield {**draft, "attachments": paths}


class Followup:
    def __init__(self, queue):
        self.queue = queue

    @contextmanager
    def transaction(self, dossier):
        with self.queue.connect() as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (dossier,)
            )
            yield db

    def present(self, dossier, question, data):
        with self.transaction(dossier) as db:
            db.execute(
                """INSERT INTO applications.followup_reviews(dossier_id,question_id,version,draft)
                   VALUES (%s,%s,%s,%s)""",
                (dossier, question, version(data), Jsonb(data)),
            )

    def approve(self, dossier, question, digest):
        with self.transaction(dossier) as db:
            return bool(
                db.execute(
                    """UPDATE applications.followup_reviews SET approved_at=COALESCE(approved_at,now())
                   WHERE question_id=%s AND version=%s AND sequence=(
                       SELECT max(sequence) FROM applications.followup_reviews WHERE dossier_id=%s)
                   RETURNING question_id""",
                    (question, digest, dossier),
                ).fetchone()
            )

    def attempt(self, dossier):
        with self.queue.connect() as db:
            return db.execute(
                "SELECT attempt_id,version,receipt FROM applications.followup_sends WHERE dossier_id=%s",
                (dossier,),
            ).fetchone()

    def claim(self, dossier, question, digest, attempt):
        with self.transaction(dossier) as db:
            return bool(
                db.execute(
                    """INSERT INTO applications.followup_sends(dossier_id,question_id,version,attempt_id)
                   SELECT dossier_id,question_id,version,%s FROM applications.followup_reviews
                   WHERE question_id=%s AND approved_at IS NOT NULL AND version=%s
                     AND sequence=(SELECT max(sequence) FROM applications.followup_reviews WHERE dossier_id=%s)
                   ON CONFLICT (dossier_id) DO NOTHING RETURNING attempt_id""",
                    (attempt, question, digest, dossier),
                ).fetchone()
            )

    def confirm(self, attempt, receipt):
        with self.queue.connect() as db:
            db.execute(
                "UPDATE applications.followup_sends SET receipt=COALESCE(receipt,%s) WHERE attempt_id=%s",
                (Jsonb(receipt), attempt),
            )
