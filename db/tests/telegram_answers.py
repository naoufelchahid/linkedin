"""Recette locale du dialogue Telegram, des checkpoints et des versions SQL."""

import os
import tempfile

from linkedin_applications.connectors import Telegram
from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner
from linkedin_applications.worker import Worker


class BotFixture(Telegram):
    def __init__(self):
        self.chat = 7
        self.sent = []
        self.updates = []

    def call(self, method, payload):
        if method == "getUpdates":
            return [
                row for row in self.updates if row["update_id"] >= payload["offset"]
            ]
        if method == "answerCallbackQuery":
            return True
        assert method == "sendMessage"
        self.sent.append(payload)
        return {"message_id": len(self.sent)}

    def update(self, **value):
        self.updates.append({"update_id": len(self.updates) + 1, **value})

    def answer(self, prompt, message_id, value):
        self.update(
            message={
                "chat": {"id": self.chat},
                "from": {"id": self.chat},
                "message_id": message_id,
                "reply_to_message": {"message_id": prompt},
                "text": value,
            }
        )

    def click(self, source, index):
        keyboard = self.sent[source - 1]["reply_markup"]["inline_keyboard"]
        assert [r[0]["text"] for r in keyboard] == [
            "Cette soumission uniquement",
            "Toutes mes futures soumissions",
        ]
        self.update(
            callback_query={
                "id": "test",
                "from": {"id": self.chat},
                "message": {"chat": {"id": self.chat}, "message_id": source},
                "data": keyboard[index][0]["callback_data"],
            }
        )


class Portal:
    native_submission = True

    def run_form(self, state, memory):
        field = "Ville ?" if state["offer"]["title"] != "B" else "Disponible ?"
        known = [r for r in memory if r["text"] == field]
        if known:
            return {"receipt": {"reference": "test"}}
        return {
            "kind": "question",
            "text": field,
            "scope": "France",
            "transmission_attempted": False,
        }


class Writer:
    def draft(self, state):
        return None


def clone(queue, title):
    with queue.connect() as db:
        record = db.execute(
            """INSERT INTO applications.dossiers
               (id,candidate,identity,mode,cycle_id,version_id,canonical_url,content,cv_sha256,uncertain)
               SELECT gen_random_uuid(),candidate,%s,mode,cycle_id,version_id,canonical_url,
                      content || jsonb_build_object('title',%s::text,'company','Atelier'),cv_sha256,uncertain
               FROM applications.dossiers WHERE candidate=%s AND identity<>'B' AND identity<>'C' LIMIT 1
               RETURNING id""",
            (title, title, queue.candidate),
        ).fetchone()
        db.execute(
            """INSERT INTO applications.lot_dossiers SELECT id,%s,99 FROM applications.lots WHERE candidate=%s""",
            (record["id"], queue.candidate),
        )
        return str(record["id"])


def exercise(directory):
    queue = PostgresQueue(
        directory, os.environ["APPLICATIONS_POSTGRES_DSN"], "recette-dialogue"
    )
    queue.launch(None, "a" * 32, "production")
    first = queue.items()[0]["dossier"]
    second = clone(queue, "B")
    bot = BotFixture()

    def restart():
        runner = Runner(queue, Portal(), Writer(), None)
        return Worker(queue, runner, bot)

    worker = restart()
    worker.tick()
    assert (
        len(worker.pending()) == 2
        and bot.sent[1]["text"] == "B · Atelier\nDisponible ?"
    )
    bot.answer(1, 101, "Lyon")
    bot.answer(1, 102, "Lille")
    bot.answer(1, 102, "Lille")
    bot.answer(2, 103, "Non")
    worker.tick()
    assert len(worker.pending()) == 2
    assert len(bot.sent) == 5
    bot.click(3, 1)  # Première réponse corrigée.
    bot.click(5, 0)  # Deuxième dossier, usage local seulement.
    bot.click(5, 1)  # Double clic avec une portée différente.
    worker.tick()
    assert {r["dossier"] for r in worker.pending().values()} == {first}
    assert queue.submissions.receipt(second)
    worker.runner.close()

    worker = restart()
    bot.click(4, 1)
    # Panne après le commit SQL du clic, avant la reprise du checkpoint.
    resume = worker.runner.run

    def crash(item, reply=None):
        if reply:
            raise ConnectionError("panne de recette")
        return resume(item)

    worker.runner.run = crash
    try:
        worker.tick()
    except ConnectionError:
        pass
    else:
        raise AssertionError("interruption attendue")
    worker.runner.close()
    worker = restart()
    worker.tick()
    assert not worker.pending() and queue.submissions.receipt(first)
    third = clone(queue, "C")
    worker.tick()
    assert queue.submissions.receipt(third)
    with queue.connect() as db:
        rows = db.execute(
            """SELECT a.value,a.scope FROM applications.candidate_answers a
                           JOIN applications.candidate_questions q ON q.id=a.question_id
                           WHERE q.dossier_id IN (%s,%s) ORDER BY a.id""",
            (first, second),
        ).fetchall()
        assert [(r["value"], r["scope"]) for r in rows] == [
            ("Lyon", None),
            ("Lille", "global"),
            ("Non", "dossier"),
        ]
        for dossier, expected in [
            (first, ["Lille"]),
            (second, ["Non"]),
            (third, ["Lille"]),
        ]:
            rows = db.execute(
                """SELECT a.value FROM applications.submission_receipts r
                         JOIN applications.attempt_answers t ON t.attempt_id=r.attempt_id
                         JOIN applications.candidate_answers a ON a.id=t.answer_id WHERE r.dossier_id=%s""",
                (dossier,),
            ).fetchall()
            assert [r["value"] for r in rows] == expected
    worker.runner.close()


with tempfile.TemporaryDirectory() as directory:
    exercise(directory)
print(
    "Questions, corrections, portée et versions des reçus vérifiées après redémarrage."
)
