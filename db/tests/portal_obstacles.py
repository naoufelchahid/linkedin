"""Reprise depuis un checkpoint et une observation positive sur un portail synthétique."""

import os
import tempfile
from pathlib import Path

from linkedin_applications.obstacles import SIGNALS
from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner


class Portal:
    native_submission = True

    def __init__(self, signal):
        self.signal = signal
        self.cleared = self.received = False
        self.turns = self.clicks = 0

    def run_form(self, state, memory):
        self.turns += 1
        if self.cleared:
            self.clicks += 1
            return {"receipt": {"reference": "fixture"}}
        if self.signal == "http_403_apres_validation":
            self.clicks += 1
        return {
            "kind": "blocked",
            "text": "canary-sensitive",
            "signal": self.signal,
            "stage": "formulaire",
            "browser_tab": 2,
            "portal_origin": "https://fixture.invalid/path?token=canary-sensitive",
            "transmission_attempted": False,
        }

    def verify(self, state):
        return {"reference": "fixture"} if self.received else None

    def obstacle_cleared(self, state, diagnostic):
        assert state["browser_tab"] == 2 and diagnostic["portal"] == "fixture.invalid"
        return self.cleared


class Writer:
    def draft(self, state):
        return None


def exercise(directory, signal):
    queue = PostgresQueue(directory, os.environ["APPLICATIONS_POSTGRES_DSN"], signal)
    queue.launch(None, "a" * 32, "production")
    (item,) = queue.items()
    portal = Portal(signal)

    def history():
        with queue.connect() as db:
            row = db.execute(
                """SELECT o.* FROM applications.portal_obstacles o JOIN applications.submission_attempts a
                                ON a.id=o.attempt_id WHERE a.dossier_id=%s""",
                (item["dossier"],),
            ).fetchone()
            assert "canary-sensitive" not in str(row) and row["signal"] == signal
            return row

    runner = Runner(queue, portal, Writer(), None)
    try:
        state = runner.run(item)
        assert history()["cause"] == SIGNALS[signal][0]
        assert history()["correction_result"] == "en_attente"
        assert "canary-sensitive" not in str(state)
    finally:
        runner.close()

    runner = Runner(queue, portal, Writer(), None)
    try:
        if signal == "http_403_apres_validation":
            assert (
                state["question"]["kind"] == "uncertain"
                and history()["transmission_attempted"]
            )
            assert history()["stage"] == "validation"
            state = runner.run(item, {"id": state["question"]["id"], "choice": "retry"})
            assert state["status"] == "submission_uncertain"
            assert runner.reconcile(state)["status"] == "submission_uncertain"
            assert portal.clicks == portal.turns == 1 and not queue.submissions.receipt(
                item["dossier"]
            )
            portal.received = True
            assert runner.reconcile(state)["status"] == "submitted"
            assert (
                portal.clicks == portal.turns == 1
                and history()["correction_result"] == "recu_verifie"
            )
        else:
            state = runner.run(item, {"id": state["question"]["id"], "choice": "done"})
            assert portal.turns == 1 and portal.clicks == 0
            assert history()["correction_result"] == "non_verifie"
            portal.cleared = True
            state = runner.run(item, {"id": state["question"]["id"], "choice": "done"})
            assert (
                state["status"] == "submitted"
                and history()["correction_result"] == "etat_verifie"
            )
            assert portal.turns == 2 and portal.clicks == 1
    finally:
        runner.close()


with tempfile.TemporaryDirectory() as directory:
    for signal in SIGNALS:
        exercise(Path(directory) / signal, signal)
print(
    "Six catégories et cause inconnue vérifiées ; 403 après validation rapproché sans retransmission."
)
