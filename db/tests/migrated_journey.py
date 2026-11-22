"""Un dossier inédit traverse inscription, confirmation, dépôt et retour arrière."""

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from email.utils import format_datetime
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import psycopg
from linkedin_applications.accounts import PortalAccounts, confirm_address
from linkedin_applications.confirmations import EmailConfirmations
from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner, config
from linkedin_applications.storage import Queue
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "jobs/graphe2/tests"
ORIGIN = "https://portail.invalid"
URL = ORIGIN + "/offres/atelier-recette-21"
CV = (TESTS / "recette_browsentic/recette.pdf").read_bytes()
SHA = hashlib.sha256(CV).hexdigest()
PRIVATE = "temoin-prive-repetition-21"
OFFER = {"key": "fixture21", "url": URL, "company": "A", "title": "Atelier inédit 21"}
CYCLE = uuid4().hex


def fixture(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


account_fixture = fixture("account_fixture", TESTS / "recette_comptes/run.py")
mail_fixture = fixture("confirmation_fixture", TESTS / "recette_confirmations/run.py")


class Portal(mail_fixture.Portal):
    native_submission = True

    def run_form(self, state, memory):
        if not (self.root / "A.verified").exists():
            if not any(
                r.get("kind") == "registration" and r.get("choice") == "allow"
                for r in memory
            ):
                return {
                    "kind": "registration",
                    "text": "Créer le compte de recette ?",
                    "scope": ORIGIN,
                    "transmission_attempted": False,
                }
            self.chrome.command(cmd="open", space=0)
            asyncio.run(
                self.accounts.fill(self.chrome, None, state["dossier"], 1, memory)
            )
            assert self.chrome.command(cmd="submit") == "Créé"
            return {
                "kind": "account_confirmation",
                "browser_tab": 1,
                "transmission_attempted": False,
            }

        data = Path(self.queue.dossier_document(state["dossier"], "cv")).read_bytes()
        with closing(HTTPConnection("127.0.0.1", self.port, timeout=5)) as client:
            client.request("POST", "/dossier", data)
            assert client.getresponse().status == 201
        # Interruption après l'écriture de la preuve par le portail.
        raise ConnectionError("panne de recette")

    def verify(self, state):
        with closing(HTTPConnection("127.0.0.1", self.port, timeout=5)) as client:
            client.request("GET", "/dossier")
            reply = client.getresponse()
            return json.loads(reply.read()) if reply.status == 200 else None


class Writer:
    def draft(self, state):
        return None


def seed():
    with psycopg.connect() as pg:
        pg.execute("CREATE ROLE rehearsal_worker LOGIN IN ROLE linkedin_applications")
        pg.execute(
            "INSERT INTO documents.cv_versions(sha256,pdf,markdown,provenance) VALUES(%s,%s,%s,'fixture')",
            (SHA, CV, PRIVATE),
        )
        pg.execute(
            "INSERT INTO discovery.cycles VALUES(%s,'2026-01-01',%s,%s,'p','p','{}','done')",
            (CYCLE, SHA, PRIVATE),
        )
        pg.execute("INSERT INTO discovery.cycle_cv VALUES(%s,%s)", (CYCLE, SHA))
        pg.execute(
            "INSERT INTO discovery.versions(id,offer_key,content,canonical_url) VALUES('fixture21','fixture21',%s,%s)",
            (Jsonb(OFFER), URL),
        )
        pg.execute(
            """INSERT INTO discovery.qualifications VALUES
                   ('fixture21','fixture21',%s,'p','done','{"verdict":"retenir","incertitude":false}','')""",
            (SHA,),
        )
        pg.execute(
            "INSERT INTO discovery.cycle_items VALUES(%s,'fixture21','fixture21')",
            (CYCLE,),
        )


def round_trip(home, queue, portal, stack):
    events = []
    accepted = []

    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/dossier":
                assert not accepted and body == CV
                accepted.append(
                    {
                        "evidence": "recu-synthetique-21",
                        "cv_sha256": hashlib.sha256(body).hexdigest(),
                    }
                )
                self.send_response(201)
            else:
                assert self.path == "/runs"
                events.append(json.loads(body))
                self.send_response(200)
            self.end_headers()

        def do_PATCH(self):
            assert self.path.startswith("/runs/")
            events.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            self.send_response(200)
            self.end_headers()

        def do_GET(self):
            assert self.path == "/dossier"
            self.send_response(200 if accepted else 404)
            self.end_headers()
            if accepted:
                self.wfile.write(json.dumps(accepted[0]).encode())

    server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), Receiver))
    thread = Thread(target=server.serve_forever)
    thread.start()
    stack.callback(thread.join)
    stack.callback(server.shutdown)
    port = portal.port = server.server_port
    (item,) = queue.items()
    assert item["cv_hash"] == SHA
    key = home / "key"
    key.write_bytes(base64.b64encode(os.urandom(32)))
    key.chmod(0o600)
    confirm_address(queue, "production", mail_fixture.ADDRESS)
    portal.queue = queue
    portal.accounts = PortalAccounts(
        queue, key, [{"url": ORIGIN + "/a", "employer": "A", "space": "A"}]
    )
    proc = stack.enter_context(
        subprocess.Popen(
            [
                "node",
                TESTS / "recette_comptes/portal.cjs",
                os.environ["PLAYWRIGHT"],
                os.environ["CHROME"],
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
    )
    stack.callback(proc.stdin.close)
    portal.chrome = account_fixture.LocalPortal(proc)
    subject = "Confirmation synthétique " + secrets.token_hex(8)
    rule = {
        "provider": ORIGIN,
        "space": "A",
        "subject": subject,
        "folder": mail_fixture.FOLDER,
        "sender": "portail@example.invalid",
        "confirmed_url": ORIGIN + "/A/actif",
        "confirmed_text": "Espace A actif",
    }
    portal.confirmations = EmailConfirmations(queue, portal, ["/bin/false"], [rule])
    with closing(Runner(queue, portal, Writer(), None, trace_port=port)) as runner:
        wait = runner.run(item)
        assert wait["question"]["kind"] == "registration"
        wait = runner.run(item, {"id": wait["question"]["id"], "choice": "allow"})
        assert wait["status"] == "waiting_account_confirmation"
    code = "G15-A-" + secrets.token_hex(6)
    msg = (
        f"From: {rule['sender']}\r\nTo: {mail_fixture.ADDRESS}\r\nSubject: {subject}\r\n"
        f"Message-ID: <{uuid4().hex}@example.invalid>\r\nDate: {format_datetime(datetime.now(UTC))}\r\n\r\n{code}\r\n"
    )
    with mail_fixture.mailbox(home, [msg]) as command:
        portal.confirmations.command = command
        for _ in range(20):
            if asyncio.run(
                mail_fixture.verify_fixture_code(portal, command, rule, "A", code)
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Confirmation de recette absente")
        with closing(Runner(queue, portal, Writer(), None, trace_port=port)) as runner:
            try:
                runner.run(item)
            except ConnectionError as exc:
                assert str(exc) == "panne de recette"
            else:
                raise AssertionError("Interruption attendue")
    assert len(accepted) == 1 and queue.submissions.receipt(item["dossier"]) is None
    with closing(Runner(queue, portal, Writer(), None, trace_port=port)) as runner:
        state = runner.run(item)
        assert state["status"] == "submitted" and state["evidence"]["cv_sha256"] == SHA
        assert runner.run(item)["status"] == "submitted"
    row = queue.submissions.receipt(item["dossier"])
    assert len(accepted) == 1 and row["evidence"] == state["evidence"]
    with psycopg.connect() as pg:
        assert pg.execute(
            "SELECT count(*) FROM applications.submission_receipts WHERE dossier_id=%s",
            (item["dossier"],),
        ).fetchone() == (1,)
        assert pg.execute(
            """SELECT a.status FROM applications.portal_accounts a JOIN applications.dossier_portal_accounts l
                              ON l.account_id=a.id WHERE l.dossier_id=%s""",
            (item["dossier"],),
        ).fetchone() == ("actif",)
    for event in events:
        assert not event.get("inputs") and not event.get("outputs")
        assert set(event) <= {
            "session_name",
            "run_type",
            "inputs",
            "extra",
            "id",
            "name",
            "start_time",
            "parent_run_id",
            "end_time",
            "outputs",
            "error",
        }
        if "extra" in event:
            assert set(event["extra"]["metadata"]) == {
                "thread_id",
                "dossier_id",
                "attempt_id",
                "mode",
            }
    serial = json.dumps(events)
    assert not any(
        v in serial
        for v in (
            PRIVATE,
            code,
            URL,
            mail_fixture.ADDRESS,
            subject,
            accepted[0]["evidence"],
        )
    )
    children = {e["name"] for e in events if e.get("parent_run_id") == row["id"]}
    assert {"graphe2.transmission", "graphe2.reprise", "graphe2.recu_sql"} <= children
    return item, row


def rollback_new_receipt(directory, item, row):
    """Replacer le reçu SQL sous la clé de dossier calculée par l’ancien G2."""
    legacy = Queue(directory / "applications")
    thread = hashlib.sha256(URL.encode()).hexdigest()
    pdf = directory / "discovery/snapshots" / (SHA + ".pdf")
    pdf.write_bytes(CV)
    # Reporter aussi l'offre, le cycle et la qualification apparus après la copie.
    with (
        psycopg.connect() as pg,
        sqlite3.connect(directory / "discovery/discovery.sqlite3") as discovery,
    ):
        cycle = pg.execute(
            "SELECT * FROM discovery.cycles WHERE id=%s", (CYCLE,)
        ).fetchone()
        discovery.execute("INSERT INTO cycles VALUES(?,?,?,?,?,?,?,?)", cycle)
        version = pg.execute(
            "SELECT id,offer_key,id,content::text,created_at::text FROM discovery.versions WHERE id=%s",
            (item["version"],),
        ).fetchone()
        discovery.execute("INSERT INTO versions VALUES(?,?,?,?,?)", version)
        qualification = pg.execute(
            "SELECT * FROM discovery.qualifications WHERE version_id=%s",
            (item["version"],),
        ).fetchone()
        discovery.execute(
            "INSERT INTO qualifications VALUES(?,?,?,?,?,?,?)", qualification
        )
        discovery.execute(
            "INSERT INTO cycle_items VALUES(?,?,?)",
            (CYCLE, version[0], qualification[0]),
        )
    delta = {**item, "dossier": thread, "cv": str(pdf)}
    with sqlite3.connect(legacy.path) as db:
        lot = db.execute(
            "INSERT INTO lots(cycle,mode) VALUES(?,?) RETURNING id",
            (CYCLE, item["mode"]),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO items VALUES(?,?,0,?)", (lot, thread, json.dumps(delta))
        )
    with closing(Runner(legacy, None, None, None)) as runner:
        runner.graph.update_state(
            config(thread),
            {
                **delta,
                "status": "submitted",
                "submission": {"id": row["id"], "status": "confirmed"},
                "evidence": row["evidence"],
                "next_node": "__end__",
            },
            as_node="draft",
        )
    # La lecture de l'ancien worker doit trouver le reçu sans tour navigateur.
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
from contextlib import closing
from pathlib import Path
import sys
from linkedin_applications.storage import Queue
from linkedin_applications.runner import Runner
q=Queue(Path(sys.argv[1]))
(item,)=[row for row in q.items() if row["dossier"]==sys.argv[2]]
with closing(Runner(q,None,None,None)) as runner:
    state=runner.run(item)
    assert state["status"]=="submitted" and state["evidence"]["evidence"]=="recu-synthetique-21"
""",
            str(legacy.data),
            thread,
        ],
        check=True,
        env={**os.environ, "PYTHONPATH": os.environ["ROLLBACK_G2_SRC"]},
    )


def main(directory):
    assert {
        s.split(":")[0].strip()
        for s in Path("/proc/net/dev").read_text().splitlines()[2:]
    } == {"lo"}
    seed()
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        home = Path(tmp)
        dsn = "dbname=rehearsal_21 user=rehearsal_worker"
        queue = PostgresQueue(home, dsn, "synthetic21")
        # Le mode métier production est exercé dans l'espace réseau loopback.
        queue.launch(None, CYCLE, "production")
        assert not PostgresQueue(home, dsn, "restored").items()
        item, receipt = round_trip(home, queue, Portal(home), stack)
        rollback_new_receipt(directory, item, receipt)
    print(
        "Compte confirmé, PDF exact, panne après acceptation, reçu SQL unique et trace expurgée."
    )
    print("Le worker antérieur retrouve le nouveau reçu au retour arrière.")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
