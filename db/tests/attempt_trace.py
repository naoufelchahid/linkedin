"""Deux processus de worker en recette, portail et réception LangSmith sur loopback."""

import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import UUID

from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner
from linkedin_applications.worker import Worker, settings

PRIVATE = "temoin-prive-cv-cookie-code-et-lien"


class LocalPortal:
    native_submission = True

    def __init__(self, marker, crash):
        self.marker = marker
        self.crash = crash

    def run_form(self, state, memory):
        assert not self.marker.exists()
        self.marker.write_text(PRIVATE)
        if self.crash:
            raise ConnectionError(PRIVATE)
        return {"receipt": {"reference": PRIVATE}}

    def verify(self, state):
        return {"reference": self.marker.read_text()} if self.marker.exists() else None


class LocalWriter:
    def draft(self, state):
        return None


class LocalTelegram:
    def call(self, method, args):
        assert method == "getUpdates"
        return []


def drive(directory, candidate, phase):
    queue = PostgresQueue(directory, os.environ["APPLICATIONS_POSTGRES_DSN"], candidate)
    queue.launch(None, "a" * 32, "production")
    runner = Runner(
        queue,
        LocalPortal(directory / "clic", phase == "crash"),
        LocalWriter(),
        None,
        trace_port=settings(directory)["APPLICATIONS_TRACE_LOCAL_PORT"],
    )
    try:
        Worker(queue, runner, LocalTelegram()).tick()
    finally:
        runner.close()


def scenario(directory, candidate, port, phases):
    for phase in phases:
        subprocess.run(
            [sys.executable, __file__, str(directory), candidate, phase],
            env={**os.environ, "APPLICATIONS_TRACE_LOCAL_PORT": str(port)},
            check=True,
        )
    queue = PostgresQueue(directory, os.environ["APPLICATIONS_POSTGRES_DSN"], candidate)
    (item,) = queue.items()
    row = queue.submissions.receipt(item["dossier"])
    assert row["evidence"]["reference"] == PRIVATE
    return str(UUID(item["dossier"])), str(UUID(row["id"]))


def check():
    events = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def receive(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            assert PRIVATE.encode() not in body
            events.append((self.command, self.path, json.loads(body)))
            self.send_response(200)
            self.end_headers()

        do_POST = do_PATCH = receive

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            port = server.server_port
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                dossier, attempt = scenario(
                    root / "reprise", "trace_reprise", port, ["crash", "resume"]
                )
            finally:
                server.shutdown()
                thread.join()
        scenario(root / "panne", "trace_panne", port, ["success"])
    runs = {}
    for method, path, body in events:
        if method == "POST":
            assert path == "/runs"
            assert set(body) <= {
                "session_name",
                "run_type",
                "inputs",
                "extra",
                "id",
                "name",
                "start_time",
                "parent_run_id",
            }
            assert body["session_name"] == "graphe2-recette" and body["inputs"] == {}
            assert body["extra"] == {
                "metadata": {
                    "dossier_id": dossier,
                    "attempt_id": attempt,
                    "thread_id": dossier,
                    "mode": "production",
                }
            }
            assert body["id"] == attempt or body["parent_run_id"] == attempt
            runs.setdefault(body["id"], body.copy())
        else:
            assert (
                set(body) <= {"end_time", "outputs", "error"} and body["outputs"] == {}
            )
            runs[path.split("/")[-1]].update(body)
    assert runs[attempt]["name"] == "graphe2.tentative"
    assert {r["name"] for r in runs.values()} == {
        "graphe2.tentative",
        "graphe2.transmission",
        "graphe2.reprise",
        "graphe2.recu_sql",
    }
    assert all(r.get("end_time") for r in runs.values())
    assert [r["error"] for r in runs.values() if r.get("error")] == ["interruption"]
    print(
        "Trace locale et trois sous-étapes corrélées après redémarrage ; reçu SQL préservé collecteur arrêté."
    )


if __name__ == "__main__":
    if len(sys.argv) == 4:
        drive(Path(sys.argv[1]), *sys.argv[2:])
    else:
        check()
