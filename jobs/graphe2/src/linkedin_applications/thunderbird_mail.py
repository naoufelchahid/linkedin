"""Envoi par le rédacteur via le compte Thunderbird autorisé."""

import asyncio
import json
from base64 import b64encode
from pathlib import Path

from jsonschema.exceptions import ValidationError

from .codex import Codex, ConnectorError, Session, codex_environment
from .writer import schema


class ThunderbirdMail:
    def __init__(self, data, command, sender):
        self.agent = Codex(Path(data) / "writer")
        self.command = command
        self.sender = sender

    def send(self, draft, attempt):
        if not self.command or not self.sender:
            return None
        return asyncio.run(self.send_async(draft))

    async def send_async(self, draft):
        called = False
        receipt = None

        async def send_approved(name, arguments):
            nonlocal called, receipt
            if name != "send_approved_mail" or arguments or called:
                return {"success": False, "contentItems": []}
            called = True
            async with (
                asyncio.timeout(100),
                Session(self.command, self.agent.cwd, codex_environment()) as rpc,
            ):
                await rpc.request(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "linkedin_applications",
                            "version": "0.1.0",
                        },
                    },
                )
                await rpc.write({"method": "notifications/initialized"})
                attachments = [
                    {
                        "name": path.name,
                        "contentType": "application/pdf",
                        "base64": b64encode(path.read_bytes()).decode("ascii"),
                    }
                    for path in map(Path, draft["attachments"])
                ]
                reply = await rpc.request(
                    "tools/call",
                    {
                        "name": "sendMail",
                        "arguments": {
                            "from": self.sender,
                            "to": draft["recipient"],
                            "subject": draft["subject"],
                            "body": draft["body"],
                            "isHtml": False,
                            "attachments": attachments,
                            "includeSignature": False,
                            "skipReview": True,
                        },
                    },
                )
                if not reply.get("isError"):
                    result = reply.get("structuredContent")
                    if result is None and reply.get("content"):
                        result = json.loads(reply["content"][0]["text"])
                    if isinstance(result, dict) and result.get("success") is True:
                        receipt = {"transport": "thunderbird", "status": "sent"}
            return {
                "success": receipt is not None,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": "Thunderbird confirme l’envoi."
                        if receipt
                        else "Envoi non confirmé.",
                    }
                ],
            }

        try:
            await self.agent.turn(
                "Le candidat a approuvé le dernier brouillon, déjà figé avec ses pièces. "
                "Appelle send_approved_mail une seule fois pour envoyer cette version via "
                "Thunderbird. Retourne ensuite si l’envoi a été confirmé.",
                schema(confirmed="boolean"),
                tools=[
                    {
                        "name": "send_approved_mail",
                        "description": "Envoyer la version approuvée, sans modifier ses champs.",
                        "inputSchema": schema(),
                    }
                ],
                call=send_approved,
            )
        except (ConnectorError, OSError, TimeoutError, ValueError, ValidationError):
            # Un échec après le départ de la requête ne permet pas de conclure à l’absence d’envoi.
            pass
        return receipt

    def verify(self, draft, attempt):
        # sendMail ne fournit pas l’identifiant du message si la réponse se perd.
        # Le dossier reste à vérifier sans déclencher un second envoi.
        return None
