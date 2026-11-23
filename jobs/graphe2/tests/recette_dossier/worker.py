"""Pilote déterministe du tour navigateur, avec le MCP réel et le workflow SQL."""

import asyncio
import json
import os
import subprocess
import sys
import traceback
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from linkedin_applications.browser import AGENT_RESULT
from linkedin_applications.codex import Codex, ConnectorError, Session
from linkedin_applications.connectors import private_write
from linkedin_applications.graph import fingerprint
from linkedin_applications.postgres_queue import PostgresQueue
from linkedin_applications.worker import Worker, services

Q = Path("/recette")
BASE, PORTAL_TOKEN = sys.argv[1:]
TITLE = "Analyste de données"
COMPANY = "Atelier Atlas"
RECIPIENT = "recrutement@example.invalid"


class TelegramFixture:
    def __init__(self):
        self.files = []
        self.messages = []

    def call(self, method, payload, files=None):
        if method == "getUpdates":
            return []
        assert str(payload["chat_id"]) == "1"
        if method == "sendDocument":
            self.files.append(sha256(files["document"].read()).hexdigest())
            return {"message_id": len(self.files)}
        assert method == "sendMessage" and files is None
        self.messages.append(payload)
        return {"message_id": len(self.files) + len(self.messages)}


class NoMail:
    def __getattr__(self, name):
        raise AssertionError("Appel de messagerie inattendu")


async def run_browser(browser, queue, schema, call):
    assert schema == AGENT_RESULT
    (item,) = queue.items()
    url = item["offer"]["url"]
    assert url == BASE + "/offre"
    origin = urlsplit(url)
    assert origin.scheme == "http" and origin.hostname == "127.0.0.1"
    result = {
        "kind": "letter",
        "text": "Lettre demandée",
        "scope": "dossier",
        "transmission_attempted": False,
        "evidence": "",
        "confirmation_url": "",
        "sent_at": "",
        "signal": "aucun",
        "stage": "piece",
        "portal_origin": BASE,
    }

    async with Session(browser.command, browser.cwd) as rpc:
        await browser.connect(rpc)
        tools = (await rpc.request("tools/list"))["tools"]
        (attach,) = [tool for tool in tools if tool["name"] == "page_attachFile"]
        assert {"expectedSha256", "expectedUrl"} <= attach["inputSchema"][
            "properties"
        ].keys(), (
            "La copie Browsentic connectée ne fournit pas les deux contrôles de pièce"
        )

        async def invoke(name, **arguments):
            return browser.json_result(await browser.use(rpc, name, arguments))

        tab = await browser.select(rpc, item)
        result["browser_tab"] = tab

        async def expect(marker, current=url):
            for _ in range(40):
                if await browser.current_url(rpc, tab) == current:
                    text = await invoke("page_extractText")
                    if marker in (text.get("text") or text.get("content", "")):
                        return
                await asyncio.sleep(0.15)
            raise AssertionError("Marqueur Chrome absent : " + marker)

        await expect(TITLE)
        await expect(COMPANY)
        await expect("Lettre obligatoire")
        letter = queue.dossier_document(item["dossier"], "letter")
        if letter is None:
            return result
        cv = queue.dossier_document(item["dossier"], "cv")
        assert cv == Path(item["cv"])
        assert fingerprint(cv) == item["cv_hash"]
        pdf_text = await asyncio.to_thread(
            subprocess.check_output, ["pdftotext", str(letter), "-"], text=True
        )
        assert COMPANY in pdf_text and TITLE in " ".join(pdf_text.split())
        print("Lettre rendue par LibreOffice et ciblage vérifié.", flush=True)

        def publish(name, data):
            (Q / (name + ".pdf")).write_bytes(data)
            return BASE + "/piece/" + name + ".pdf?recette=" + PORTAL_TOKEN

        refs = {}
        for kind, path in (("cv", cv), ("letter", letter)):
            refs[kind] = {
                "downloadId": (
                    await invoke(
                        "page_captureDownload", url=publish(kind, path.read_bytes())
                    )
                )["downloadId"]
            }

        # A synthetic negative control contains no bytes copied from the CV.
        header = b"%PDF-1.4\n% fixture\n"
        other = header.ljust(cv.stat().st_size, b" ")
        assert len(other) == cv.stat().st_size and other != cv.read_bytes()
        wrong = await invoke("page_captureDownload", url=publish("autre", other))
        cv_digest, letter_digest = fingerprint(cv), fingerprint(letter)

        def register(cv_reference):
            private_write(
                Q / "policy.json",
                json.dumps(
                    {"files": {cv_digest: cv_reference, letter_digest: refs["letter"]}}
                ),
            )

        async def attach_piece(kind):
            return await call(
                "attach_dossier_document",
                {"tab": tab, "url": url, "piece": kind, "selector": "#" + kind},
            )

        register({"downloadId": wrong["downloadId"]})
        rejected = await attach_piece("cv")
        assert not rejected["success"]
        assert rejected["contentItems"][0]["text"] == "browsentic_page_attachFile"
        await expect("cv: vide")
        register(refs["cv"])
        for kind, digest in (("cv", cv_digest), ("letter", letter_digest)):
            assert (await attach_piece(kind))["success"]
            await expect(kind + ": " + digest)
        print(
            "Mauvaise référence refusée. Empreintes des deux champs Chrome vérifiées.",
            flush=True,
        )
        assert await browser.current_url(rpc, tab) == url
        await browser.use(
            rpc, "page_clickElement", {"target": {"selector": "#deposer"}}
        )
        receipt_url = BASE + "/recu"
        await expect("RECETTE-ATLAS — " + TITLE, receipt_url)
        result.update(
            kind="submitted",
            text="",
            evidence="RECETTE-ATLAS — " + TITLE,
            confirmation_url=receipt_url,
            transmission_attempted=True,
            stage="confirmation",
        )
        return result


async def synthetic_writing(codex, task, schema):
    if "paragraphs" in schema["properties"]:
        return {
            "subject": f"{TITLE} — {COMPANY}",
            "paragraphs": [
                f"Je vous présente ma candidature au poste « {TITLE} » chez {COMPANY}."
            ],
        }
    assert "recipient" in schema["properties"]
    return {
        "recipient": RECIPIENT,
        "subject": f"Suivi de candidature — {TITLE}",
        "body": "Bonjour,\nJe vous transmets le dossier de recette.\n"
        "Les deux pièces sont jointes.\nMerci pour votre lecture.",
    }


def main():
    queue = PostgresQueue(
        Q / "etat", os.environ["APPLICATIONS_POSTGRES_DSN"], "recette"
    )
    runner, telegram = services(queue, os.environ)
    browser = runner.workflow.browser
    telegram_fixture = TelegramFixture()
    worker = Worker(queue, runner, telegram)

    async def turn(task, schema, tools, call, *, mcp):
        assert "Données du dossier" in task and mcp[0] == browser.command
        try:
            return await run_browser(browser, queue, schema, call)
        except ConnectorError as exc:
            print("Échec du MCP de recette :", str(exc), file=sys.stderr)
            raise

    def run_form(state, memory):
        result = original_run_form(state, memory)
        if result["kind"] == "submitted":
            # The native turn accepts only HTTPS receipts. The fixture stays on HTTP
            # loopback and uses the policy verifier against the actual receipt page.
            browser.verifications = [
                {
                    "origin": BASE,
                    "path": "/recu",
                    "selector": "h1",
                    "marker": "RECETTE-ATLAS",
                    "offer_fields": ["title"],
                }
            ]
            receipt = asyncio.run(browser.verify_async({**state, **result}))
            assert receipt and receipt["url"] == BASE + "/recu"
            result["receipt"] = {**receipt, "evidence": result["evidence"]}
        return result

    def diagnose(*args, **kwargs):
        try:
            return original_run(*args, **kwargs)
        except (AssertionError, ConnectorError):
            traceback.print_exc()
            raise

    original_run = runner.run
    original_run_form = browser.run_form
    try:
        with ExitStack() as patches:
            if os.getenv("RECETTE_REDACTION_LOCALE") == "1":
                patches.enter_context(patch.object(Codex, "turn", synthetic_writing))
            patches.enter_context(patch.object(browser.codex, "turn", side_effect=turn))
            patches.enter_context(
                patch.object(browser, "run_form", side_effect=run_form)
            )
            patches.enter_context(patch.object(runner, "run", side_effect=diagnose))
            patches.enter_context(
                patch.object(telegram, "call", side_effect=telegram_fixture.call)
            )
            runner.workflow.mail = NoMail()
            worker.tick()
            worker.tick()
        (state,) = worker.pending().values()
        question = state["question"]
        assert question["kind"] == "mail" and state["mail_status"] == "waiting"
        assert state["evidence"]["url"] == BASE + "/recu"
        assert state["status"] == "submitted"
        (message,) = telegram_fixture.messages
        text = message["text"]
        callbacks = [
            row[0]["callback_data"]
            for row in message["reply_markup"]["inline_keyboard"]
        ]
        assert callbacks == [f"{question['id']}:approve", f"{question['id']}:hold"]
        draft = runner.workflow.local_draft(state)
        assert draft["recipient"] == RECIPIENT
        assert all(
            part in text for part in (RECIPIENT, draft["subject"], draft["body"])
        )
        expected = [fingerprint(path) for path in draft["attachments"]]
        assert (
            telegram_fixture.files
            == expected
            == [state["cv_hash"], state["letter_hash"]]
        )
        assert question["version"] == runner.workflow.draft_version(draft)
        assert queue.followup.attempt(state["dossier"]) is None
        private_write(
            Q / "preuve.json",
            json.dumps(
                {
                    "dossier": state["dossier"],
                    "pieces": expected,
                    "recipient": RECIPIENT,
                    "subject": draft["subject"],
                    "body": draft["body"],
                    "review": question["version"],
                    "receipt": state["evidence"]["evidence"],
                },
                ensure_ascii=False,
            ),
        )
        print(
            "Reçu SQL et aperçu Telegram exact vérifiés. Suivi en attente d’accord.",
            flush=True,
        )
    finally:
        runner.close()


if __name__ == "__main__":
    main()
