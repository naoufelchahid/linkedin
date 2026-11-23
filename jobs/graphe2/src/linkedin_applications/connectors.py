"""Canaux pilotés par Python."""

import os
from pathlib import Path

import httpx

from .codex import ConnectorError


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
