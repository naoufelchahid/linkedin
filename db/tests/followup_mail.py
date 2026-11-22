"""Une réponse SMTP perdue et une correction de pièce sur des transports en mémoire."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from linkedin_applications.connectors import Mail
from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner


class Portal:
    native_submission = True

    def run_form(self, state, memory):
        return {"receipt": {"reference": "test-recu"}}


class Writer:
    def __init__(self, pdf):
        self.pdf = pdf

    def draft(self, state):
        return {
            "recipient": "local@example.invalid",
            "subject": "Suivi",
            "body": "Texte synthétique",
            "attachments": [str(self.pdf)],
        }


class Mailbox:
    def __init__(self):
        self.messages = []
        self.visible = False
        self.queries = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def login(self, *args):
        pass

    def send_message(self, message):
        self.messages.append(message)
        raise ConnectionError("Réponse SMTP perdue après acceptation")

    def select(self, folder, readonly):
        assert readonly
        return "OK", []

    def search(self, *args):
        self.queries += 1
        return "OK", [b"1 2" if self.visible else b"1"]

    def fetch(self, uid, request):
        ident = (
            self.messages[0]["Message-ID"] if uid == b"2" else "<autre@example.invalid>"
        )
        return "OK", [(b"header", f"Message-ID: {ident}\r\n\r\n".encode())]


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    q = PostgresQueue(root, os.environ["APPLICATIONS_POSTGRES_DSN"], "mail-test")
    q.launch(None, "a" * 32, "production")
    (item,) = q.items()
    pdf = root / "lettre.pdf"
    pdf.write_bytes(b"%PDF A")
    writer = Writer(pdf)
    mailbox = Mailbox()
    mail = Mail(
        {
            "APPLICATIONS_SMTP_HOST": "fixture.invalid",
            "APPLICATIONS_IMAP_HOST": "fixture.invalid",
            "APPLICATIONS_SMTP_USER": "fixture@example.invalid",
            "APPLICATIONS_SMTP_PASSWORD": "fixture",
            "APPLICATIONS_IMAP_SENT": "Sent",
        }
    )
    with (
        patch("smtplib.SMTP_SSL", return_value=mailbox),
        patch("imaplib.IMAP4_SSL", return_value=mailbox),
    ):
        runner = Runner(q, Portal(), writer, mail)
        state = runner.run(item)
        first = state["question"]
        original_approve = q.followup.approve

        def modify_after_approval(*args):
            assert original_approve(*args)
            pdf.write_bytes(b"%PDF B")
            return True

        q.followup.approve = modify_after_approval
        state = runner.run(item, {"id": first["id"], "choice": "approve"})
        second = state["question"]
        assert second["id"] != first["id"] and second["version"] != first["version"]
        assert not mailbox.messages and not q.followup.attempt(item["dossier"])
        q.followup.approve = original_approve
        assert not q.followup.approve(item["dossier"], first["id"], first["version"])
        assert (
            runner.run(item, {"id": first["id"], "choice": "approve"})["question"]
            == second
        )
        try:
            runner.run(item, {"id": second["id"], "choice": "approve"})
        except ConnectionError:
            pass
        else:
            raise AssertionError("Panne SMTP attendue")
        runner.close()
        assert len(mailbox.messages) == 1
        (part,) = mailbox.messages[0].iter_attachments()
        assert (
            part.get_payload(decode=True) == b"%PDF B"
            and part.get_filename() == "lettre.pdf"
        )
        runner = Runner(q, Portal(), writer, mail)
        state = runner.run(item)
        assert state["mail_status"] == "uncertain"
        mailbox.visible = True
        state = runner.reconcile_mail(state)
        assert state["mail_status"] == "sent" and len(mailbox.messages) == 1
        assert mailbox.queries == 2
        ledger = q.followup.attempt(item["dossier"])
        assert ledger["receipt"]["message_id"] == mailbox.messages[0]["Message-ID"]
        assert ledger["version"] == second["version"]
        runner.close()
print(
    "Nouvel accord après correction, réponse SMTP perdue et reçu IMAP exact vérifiés."
)
