"""Pannes du worker avec PostgreSQL et un portail synthétique sans réseau."""

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner


class Crash(Exception):
    pass


class Portal:
    native_submission = True

    def __init__(self):
        self.turns = self.clicks = self.reads = 0
        self.outcome = "after_click"

    def run_form(self, state, memory):
        self.turns += 1
        if self.outcome == "before_click":
            raise Crash
        self.clicks += 1
        if self.outcome == "after_click":
            raise Crash
        return {"receipt": {"reference": "fixture"}}

    def verify(self, state):
        self.reads += 1
        return {"reference": "fixture"} if self.clicks else None


class Writer:
    def draft(self, state):
        return None


def scenario(directory, crash):
    queue = PostgresQueue(directory, os.environ["APPLICATIONS_POSTGRES_DSN"], crash)
    queue.launch(None, "a" * 32, "production")
    (item,) = queue.items()
    portal = Portal()
    portal.outcome = crash
    runner = Runner(queue, portal, Writer(), None)
    if crash == "after_receipt":
        commit = queue.submissions.finish

        def fail_after_commit(*args, **kwargs):
            assert commit(*args, **kwargs)
            raise Crash

        queue.submissions.finish = fail_after_commit
    try:
        runner.run(item)
    except Crash:
        pass
    else:
        raise AssertionError("panne attendue")
    finally:
        runner.close()
    if crash == "after_receipt":
        queue.submissions.finish = commit

    runner = Runner(queue, portal, Writer(), None)
    try:
        state = runner.run(item)
        if crash == "before_click":
            assert state["question"]["kind"] == "uncertain" and portal.clicks == 0
            state = runner.run(item, {"id": state["question"]["id"], "choice": "retry"})
            assert state["status"] == "submission_uncertain"
            assert portal.turns == 1 and portal.clicks == 0
            assert not queue.submissions.receipt(item["dossier"])
            return
        assert state["status"] == "submitted"
        assert portal.turns == portal.clicks == 1
        if crash == "after_receipt":
            assert portal.reads == 0
        with queue.connect() as db:
            row = db.execute(
                """SELECT count(*) AS n FROM applications.submission_attempts a
                                JOIN applications.submission_receipts r ON a.id=r.attempt_id
                                WHERE a.dossier_id=%s AND a.status='confirmed' AND a.generation=1""",
                (item["dossier"],),
            ).fetchone()
            assert row["n"] == 1
    finally:
        runner.close()


def live_browser(directory):
    queue = PostgresQueue(
        directory, os.environ["APPLICATIONS_POSTGRES_DSN"], "live_browser"
    )
    queue.launch(None, "a" * 32, "production")
    (item,) = queue.items()
    started, release = Event(), Event()

    class LivePortal(Portal):
        def run_form(self, state, memory):
            started.set()
            assert release.wait(30)
            return super().run_form(state, memory)

    portal = LivePortal()
    portal.outcome = "accepted"
    old = Runner(queue, portal, Writer(), None)
    other = Runner(
        PostgresQueue(directory / "other", queue.dsn, queue.candidate),
        portal,
        Writer(),
        None,
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(old.run, item)
            try:
                assert started.wait(20)
                active = queue.submissions.active(item["dossier"])
                with queue.connect() as db:
                    db.execute(
                        "UPDATE applications.submission_attempts SET lease_until=now()-interval '1 minute' WHERE id=%s",
                        (active["id"],),
                    )
                assert not queue.submissions.finish(
                    {**item, "submission": active}, outcome={"status": "ready"}
                )
                waiting = other.run(item)
                assert waiting["question"]["kind"] == "uncertain"
                assert portal.clicks == 0 and not pending.done()
            finally:
                release.set()
            stale = pending.result(timeout=20)
            assert stale["question"]["kind"] == "uncertain"
            assert not queue.submissions.receipt(item["dossier"])
        assert other.reconcile(waiting)["status"] == "submitted"
        assert portal.clicks == portal.turns == 1
    finally:
        old.close()
        other.close()


with tempfile.TemporaryDirectory() as tmp:
    for case in ("before_click", "after_click", "after_receipt"):
        scenario(Path(tmp) / case, case)
    live_browser(Path(tmp) / "live")
print(
    "Pannes avant clic, après acceptation et après reçu SQL vérifiées ; bail expiré et ancien navigateur actif sans second tour."
)
