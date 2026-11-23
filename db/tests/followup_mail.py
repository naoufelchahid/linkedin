"""Une réponse Thunderbird perdue après l’approbation d’une pièce modifiée."""

import os
import tempfile
from base64 import b64decode
from pathlib import Path
from unittest.mock import patch

from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.runner import Runner
from linkedin_applications.thunderbird_mail import ThunderbirdMail


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
        self.confirm = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def write(self, message):
        assert message["method"] == "notifications/initialized"

    async def request(self, method, params):
        if method == "initialize":
            return {}
        assert method == "tools/call" and params["name"] == "sendMail"
        self.messages.append(params["arguments"])
        if self.confirm:
            return {"structuredContent": {"success": True, "message": "Message sent"}}
        raise ConnectionError("Réponse Thunderbird perdue après acceptation")


async def agent_turn(task, schema, tools, call):
    tool = tools[0]["name"]
    assert not (await call(tool, {"to": "other@example.invalid"}))["success"]
    result = await call(tool, {})
    assert not (await call(tool, {}))["success"]
    return {"confirmed": result["success"]}


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    q = PostgresQueue(root, os.environ["APPLICATIONS_POSTGRES_DSN"], "mail-test")
    q.launch(None, "a" * 32, "production")
    (item,) = q.items()
    pdf = root / "lettre.pdf"
    pdf.write_bytes(b"%PDF A")
    writer = Writer(pdf)
    mailbox = Mailbox()
    mail = ThunderbirdMail(root, ["fixture"], "fixture@example.invalid")
    with (
        patch.object(mail.agent, "turn", side_effect=agent_turn),
        patch("linkedin_applications.thunderbird_mail.Session", return_value=mailbox),
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
        state = runner.run(item, {"id": second["id"], "choice": "approve"})
        assert state["mail_status"] == "uncertain"
        runner.close()
        (sent,) = mailbox.messages
        assert sent["from"] == "fixture@example.invalid"
        assert sent["to"] == "local@example.invalid"
        assert sent["subject"] == "Suivi" and sent["body"] == "Texte synthétique"
        assert sent["skipReview"] and not sent["includeSignature"]
        (part,) = sent["attachments"]
        assert b64decode(part["base64"]) == b"%PDF B" and part["name"] == "lettre.pdf"

        runner = Runner(q, Portal(), writer, mail)
        state = runner.run(item)
        assert state["mail_status"] == "uncertain"
        state = runner.reconcile_mail(state)
        assert state["mail_status"] == "uncertain" and len(mailbox.messages) == 1
        ledger = q.followup.attempt(item["dossier"])
        assert ledger["receipt"] is None and ledger["version"] == second["version"]
        runner.close()

        mailbox.confirm = True
        receipt = mail.send(writer.draft({}), "fixture-confirmation")
        assert receipt == {"transport": "thunderbird", "status": "sent"}
        assert len(mailbox.messages) == 2

print("Version approuvée, agent, identité Thunderbird et absence de réenvoi vérifiés.")
