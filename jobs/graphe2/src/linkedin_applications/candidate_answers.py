"""Questions et versions de réponses. Le clic fixe la portée avant toute reprise."""

from psycopg.types.json import Jsonb


class CandidateAnswers:
    def __init__(self, queue):
        self.queue = queue

    def open(self, state):
        q = state["question"]
        with self.queue.connect() as db:
            db.execute(
                """INSERT INTO applications.candidate_questions (id,dossier_id,prompt,context)
                   VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                (q["id"], state["dossier"], q["text"], Jsonb(q.get("scope", {}))),
            )

    @staticmethod
    def lock(db, question):
        db.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 13))", (question,)
        )
        return db.execute(
            "SELECT id FROM applications.candidate_questions WHERE id=%s",
            (question,),
        ).fetchone()

    def stage(self, question, text, message):
        with self.queue.connect() as db:
            if not self.lock(db, question):
                return None
            current = db.execute(
                """SELECT id,source_message_id,button_message_id,scope FROM applications.candidate_answers
                   WHERE question_id=%s ORDER BY id DESC LIMIT 1""",
                (question,),
            ).fetchone()
            if current:
                if current["scope"] or current["source_message_id"] > message:
                    return None
                if current["source_message_id"] == message:
                    return (
                        current["id"] if current["button_message_id"] is None else None
                    )
            return db.execute(
                """INSERT INTO applications.candidate_answers(question_id,value,source_message_id)
                   VALUES (%s,%s,%s) RETURNING id""",
                (question, text, message),
            ).fetchone()["id"]

    def bind_buttons(self, revision, message):
        with self.queue.connect() as db:
            db.execute(
                """UPDATE applications.candidate_answers SET button_message_id=%s
                          WHERE id=%s AND scope IS NULL""",
                (message, revision),
            )

    def confirm(self, question, revision, message, choice):
        scope = {"remember": "global", "once": "dossier"}[choice]
        with self.queue.connect() as db:
            if not self.lock(db, question):
                return
            db.execute(
                """UPDATE applications.candidate_answers SET scope=%s, decided_at=clock_timestamp()
                   WHERE question_id=%s AND id=%s AND button_message_id=%s AND scope IS NULL
                   AND id=(SELECT max(id) FROM applications.candidate_answers WHERE question_id=%s)""",
                (scope, question, revision, message, question),
            )

    def reply(self, question):
        with self.queue.connect() as db:
            row = db.execute(
                """SELECT id,value,scope FROM applications.candidate_answers
                   WHERE question_id=%s AND scope IS NOT NULL""",
                (question,),
            ).fetchone()
        if row:
            return {
                "id": question,
                "choice": "remember" if row["scope"] == "global" else "once",
                "text": row["value"],
                "answer_version": row["id"],
            }

    def read(self, state):
        with self.queue.connect() as db:
            rows = db.execute(
                """SELECT DISTINCT ON (q.prompt,q.context) a.id AS answer_version,
                          q.prompt AS text,q.context AS context,a.value AS answer,a.scope,
                          q.dossier_id::text AS dossier
                   FROM applications.candidate_questions q
                   JOIN applications.candidate_answers a ON a.question_id=q.id
                   JOIN applications.dossiers source ON source.id=q.dossier_id
                   JOIN applications.dossiers target ON target.id=%s
                   WHERE source.candidate=target.candidate AND source.mode=target.mode
                     AND a.scope IS NOT NULL AND (source.id=target.id OR a.scope='global')
                   ORDER BY q.prompt,q.context,(source.id=target.id) DESC,a.decided_at DESC,a.id DESC""",
                (state["dossier"],),
            ).fetchall()
            attempt = state.get("submission") or {}
            if attempt.get("generation"):
                db.cursor().executemany(
                    """INSERT INTO applications.attempt_answers(attempt_id,answer_id)
                       VALUES(%s,%s) ON CONFLICT DO NOTHING""",
                    [(attempt["id"], row["answer_version"]) for row in rows],
                )
        return [dict(row, kind="question") for row in rows]
