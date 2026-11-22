"""Autorisation unique d'un tour de transmission et preuves de dépôt durables."""

from contextlib import contextmanager
from threading import Event, Thread

import psycopg
from psycopg.types.json import Jsonb


class Submissions:
    def __init__(self, queue, lease_seconds=120):
        self.queue = queue
        self.lease_seconds = lease_seconds

    def receipt(self, dossier):
        with self.queue.connect() as db:
            row = db.execute(
                """SELECT r.attempt_id::text AS id, r.evidence FROM applications.submission_receipts r
                   JOIN applications.dossiers d ON d.id=r.dossier_id WHERE d.id=%s AND d.candidate=%s""",
                (dossier, self.queue.candidate),
            ).fetchone()
            return row

    def active(self, dossier):
        with self.queue.connect() as db:
            return db.execute(
                """SELECT a.id::text, a.generation FROM applications.submission_attempts a
                   JOIN applications.dossiers d ON d.id=a.dossier_id WHERE d.id=%s
                   AND d.candidate=%s AND a.status='transmitting'""",
                (dossier, self.queue.candidate),
            ).fetchone()

    def begin(self, state):
        dossier, requested = state["dossier"], state["submission"]["id"]
        with self.queue.connect() as db:
            # Le verrou transactionnel porte sur le dossier, même si celui-ci n'a encore aucune tentative.
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (dossier,)
            )
            row = db.execute(
                """SELECT id::text, generation,status,outcome FROM applications.submission_attempts
                   WHERE dossier_id=%s AND (status<>'no_submission' OR id=%s)
                   ORDER BY generation DESC LIMIT 1""",
                (dossier, requested),
            ).fetchone()
            if row:
                return False, row
            row = db.execute(
                """INSERT INTO applications.submission_attempts
                   (id,dossier_id,generation,version_id,cv_sha256,letter_sha256,lease_until,status)
                   SELECT %s,d.id,1+COALESCE((SELECT max(generation) FROM applications.submission_attempts
                          WHERE dossier_id=d.id),0),d.version_id,d.cv_sha256,l.sha256,
                          clock_timestamp()+%s * interval '1 second','transmitting'
                   FROM applications.dossiers d LEFT JOIN documents.dossier_letters l ON l.dossier_id=d.id
                   WHERE d.id=%s AND d.candidate=%s AND d.mode='production'
                   RETURNING id::text,generation,status""",
                (requested, self.lease_seconds, dossier, self.queue.candidate),
            ).fetchone()
            if not row:
                raise ValueError("submission_dossier_invalid")
            return True, row

    @contextmanager
    def lease(self, dossier, attempt):
        stopped = Event()

        def renew():
            while not stopped.wait(self.lease_seconds / 3):
                try:
                    with self.queue.connect() as db:
                        updated = db.execute(
                            """UPDATE applications.submission_attempts SET lease_until=
                               clock_timestamp()+%s * interval '1 second' WHERE dossier_id=%s AND id=%s
                               AND generation=%s AND status='transmitting' AND lease_until>clock_timestamp()""",
                            (
                                self.lease_seconds,
                                dossier,
                                attempt["id"],
                                attempt["generation"],
                            ),
                        ).rowcount
                    if not updated:
                        break
                except psycopg.Error:
                    break

        thread = Thread(target=renew, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join()

    def finish(self, state, *, evidence=None, outcome=None, reconciled=False):
        """Un résultat du tour appartient au bail vivant. Une preuve relue peut clôturer un bail expiré."""
        attempt = state["submission"]
        with self.queue.connect() as db:
            row = db.execute(
                """UPDATE applications.submission_attempts SET status=%s,outcome=%s
                   WHERE dossier_id=%s AND id=%s AND generation=%s AND status='transmitting'
                   AND (lease_until>clock_timestamp() OR %s) RETURNING id""",
                (
                    "confirmed" if evidence else "no_submission",
                    Jsonb(outcome) if outcome else None,
                    state["dossier"],
                    attempt["id"],
                    attempt["generation"],
                    bool(evidence and reconciled),
                ),
            ).fetchone()
            if not row:
                return False
            if evidence:
                db.execute(
                    """INSERT INTO applications.submission_receipts(dossier_id,attempt_id,evidence)
                       VALUES (%s,%s,%s)""",
                    (state["dossier"], attempt["id"], Jsonb(evidence)),
                )
            return True
