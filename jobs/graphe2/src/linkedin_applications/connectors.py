"""Canaux pilotés par Python."""

import imaplib
import os
import smtplib
from email import message_from_bytes
from email.message import EmailMessage
from pathlib import Path

import httpx

from .codex import ConnectorError


class Mail:
    def __init__(self, env):
        self.env = env

    def message_id(self, attempt):
        sender = self.env["APPLICATIONS_SMTP_USER"]
        return f"<linkedin-{attempt}@{sender.rsplit('@', 1)[-1]}>"

    def send(self, draft, attempt):
        env = self.env
        message = EmailMessage()
        message["From"] = env["APPLICATIONS_SMTP_USER"]
        message["To"] = draft["recipient"]
        message["Subject"] = draft["subject"]
        message["Message-ID"] = self.message_id(attempt)
        message.set_content(draft["body"])
        for attachment in draft["attachments"]:
            file = Path(attachment)
            message.add_attachment(
                file.read_bytes(),
                maintype="application",
                subtype="pdf",
                filename=file.name,
            )
        with smtplib.SMTP_SSL(env["APPLICATIONS_SMTP_HOST"], timeout=30) as smtp:
            smtp.login(env["APPLICATIONS_SMTP_USER"], env["APPLICATIONS_SMTP_PASSWORD"])
            refusals = smtp.send_message(message)
        return None if refusals else {"message_id": message["Message-ID"]}

    def verify(self, draft, attempt):
        env = self.env
        if not env.get("APPLICATIONS_IMAP_SENT"):
            return None
        message_id = self.message_id(attempt)
        with imaplib.IMAP4_SSL(env["APPLICATIONS_IMAP_HOST"], timeout=30) as imap:
            imap.login(env["APPLICATIONS_SMTP_USER"], env["APPLICATIONS_SMTP_PASSWORD"])
            status, _ = imap.select(env["APPLICATIONS_IMAP_SENT"], readonly=True)
            if status != "OK":
                return None
            status, values = imap.search(
                None, "HEADER", "Message-ID", f'"{message_id}"'
            )
            if status == "OK" and values and values[0]:
                for uid in values[0].split():
                    status, parts = imap.fetch(
                        uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
                    )
                    if status == "OK" and any(
                        isinstance(part, tuple)
                        and message_from_bytes(part[1]).get("Message-ID") == message_id
                        for part in parts
                    ):
                        return {"message_id": message_id}
        return None


class Telegram:
    def __init__(self, token, chat):
        self.url = "https://api.telegram.org/bot" + token
        self.chat = int(chat)

    def call(self, method, payload, files=None):
        try:
            if files:
                response = httpx.post(
                    self.url + "/" + method, data=payload, files=files, timeout=20
                )
            else:
                response = httpx.post(self.url + "/" + method, json=payload, timeout=20)
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise ConnectorError("telegram_unavailable") from None
        if not body.get("ok"):
            raise ConnectorError("telegram_rejected")
        return body["result"]

    def text(self, text, **params):
        return self.call("sendMessage", {"chat_id": self.chat, "text": text, **params})

    def document(self, path):
        with Path(path).open("rb") as stream:
            return self.call(
                "sendDocument", {"chat_id": str(self.chat)}, files={"document": stream}
            )

    def buttons(self, text, question, choices):
        return self.text(
            text,
            reply_markup={
                "inline_keyboard": [
                    [{"text": label, "callback_data": f"{question}:{choice}"}]
                    for choice, label in choices
                ]
            },
        )


ACTIONS = {
    "obstacle": [("done", "Vérifier le correctif")],
    "challenge": [("done", "Vérification terminée")],
    "registration": [
        ("allow", "Autoriser pour ce portail"),
        ("deny", "Refuser pour ce portail"),
    ],
    "uncertain": [
        ("retry", "Autoriser une nouvelle tentative"),
        ("hold", "Laisser à vérifier"),
    ],
    "mail": [("approve", "Valider ce brouillon"), ("hold", "Mettre en attente")],
    "recipe_mail": [("approve", "Valider l’aperçu"), ("hold", "Fermer l’aperçu")],
}
RESPONSE_ACTIONS = [
    ("once", "Cette soumission uniquement"),
    ("remember", "Toutes mes futures soumissions"),
]


def private_write(path, value):
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
