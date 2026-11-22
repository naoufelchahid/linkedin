"""Deux processus Docker à disques privés se relaient après une question LangGraph."""

import os
import sys
from pathlib import Path

from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner


class Portal:
    native_submission = True

    def run_form(self, state, memory):
        if not memory:
            return {
                "kind": "question",
                "text": "Ville de recette ?",
                "transmission_attempted": False,
            }
        assert memory[0]["answer"] == "Ville test"
        return {"receipt": {"reference": "fixture-dossier"}}


class Writer:
    def draft(self, state):
        return None


phase = sys.argv[1]
directory = Path("/tmp/worker") / phase
queue = PostgresQueue(
    directory, os.environ["APPLICATIONS_POSTGRES_DSN"], "relais-checkpoint"
)
queue.launch(None, "a" * 32, "production")
(item,) = queue.items()
runner = Runner(queue, Portal(), Writer(), None)
try:
    if phase == "premier":
        letter = directory / "lettre-source.pdf"
        letter.write_bytes(b"%PDF lettre de recette")
        queue.dossier_letter(item["dossier"], letter)
        state = runner.run(item)
        assert state["question"]["kind"] == "question"
        queue.candidate_answers.open(state)
    else:
        (snapshot,) = runner.snapshots()
        assert snapshot.interrupts
        previous = Path(snapshot.values["cv"])
        assert not previous.exists()
        letter = queue.dossier_document(item["dossier"], "letter")
        draft = queue.followup.local_draft(
            item["dossier"],
            {"attachments": [str(previous), str(previous.with_name(letter.name))]},
        )
        cv, letter = map(Path, draft["attachments"])
        assert (
            cv.read_bytes() == b"%PDF A"
            and letter.read_bytes() == b"%PDF lettre de recette"
        )
        q = snapshot.values["question"]["id"]
        revision = queue.candidate_answers.stage(q, "Ville test", 71)
        queue.candidate_answers.bind_buttons(revision, 72)
        queue.candidate_answers.confirm(q, revision, 72, "once")
        state = runner.run(item, {"id": q})
        assert state["status"] == runner.run(item)["status"] == "submitted"
        with queue.connect() as db:
            assert (
                db.execute(
                    "SELECT count(*) n FROM applications.submission_receipts WHERE dossier_id=%s",
                    (item["dossier"],),
                ).fetchone()["n"]
                == 1
            )
            assert not db.execute(
                "SELECT has_schema_privilege(current_user,'runtime_g2','CREATE') OR has_schema_privilege('linkedin_web','runtime_g2','USAGE') AS excessive"
            ).fetchone()["excessive"]
    assert not (directory / "checkpoints.sqlite3").exists()
finally:
    runner.close()
