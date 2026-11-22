"""Les tours de rédaction travaillent dans le répertoire privé du dossier."""

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from .codex import Codex, ConnectorError


def schema(**properties):
    return {
        "type": "object",
        "properties": {key: {"type": value} for key, value in properties.items()},
        "required": list(properties),
        "additionalProperties": False,
    }


def dossier_context(state):
    return {key: state[key] for key in ("offer", "cv_text", "answers") if key in state}


class Writer:
    def __init__(self, data, template, humanizer=None, documents=None):
        self.documents = documents
        self.data = Path(data)
        self.template = Path(template)
        self.humanizer = Path(humanizer) if humanizer else None

    def letter(self, state):
        if self.documents and (
            saved := self.documents.dossier_letter(state["dossier"])
        ):
            return saved
        work = self.data / "documents" / state["dossier"] / uuid4().hex
        codex = Codex(work, writer=True)
        shutil.copyfile(self.template, work / "lettre.docx")
        result = asyncio.run(
            codex.turn(
                "Personnalise la copie lettre.docx dans ce dossier. Rédige en français ou anglais selon "
                "l’annonce. Adapte l’objet, l’accroche, les expériences attestées et la conclusion au "
                "contrat. Exporte en PDF sous lettre.pdf avec LibreOffice et contrôle le rendu avec Poppler. "
                "Retourne checked=true après avoir contrôlé le fichier. Données du dossier :\n"
                + json.dumps(dossier_context(state), ensure_ascii=False),
                schema(checked="boolean"),
            )
        )
        pdf = work / "lettre.pdf"
        if not result["checked"] or pdf.is_symlink() or not pdf.is_file():
            raise ConnectorError("letter_missing")
        check = subprocess.run(
            ["pdftotext", str(pdf), "-"], capture_output=True, timeout=15, check=False
        )
        if check.returncode or not check.stdout.strip():
            raise ConnectorError("letter_unreadable")
        pdf.chmod(0o600)
        if self.documents:
            return self.documents.dossier_letter(state["dossier"], pdf)
        return str(pdf)

    def draft(self, state):
        # Une adresse unique et publiée peut être proposée au rédacteur.
        addresses = set(
            re.findall(
                r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                state["offer"].get("description", ""),
            )
        )
        if not addresses:
            return None
        if not self.humanizer:
            raise ConnectorError("humanizer_not_configured")
        codex = Codex(self.data / "writer")
        result = asyncio.run(
            codex.turn(
                "Si l’annonce indique clairement une adresse de recrutement, rédige un mail d’appui "
                "de 4 à 8 lignes dans sa langue. Reprends dans l’objet le poste, la référence éventuelle "
                "et le nom confirmé. Applique les consignes Humanizer et vérifie le texte. "
                "Si l’adresse de recrutement est absente ou ambiguë, retourne recipient vide.\n"
                + self.humanizer.read_text()
                + "\nDonnées :\n"
                + json.dumps(dossier_context(state), ensure_ascii=False),
                schema(recipient="string", subject="string", body="string"),
            )
        )
        if not result["recipient"]:
            return None
        if result["recipient"] not in addresses:
            raise ConnectorError("recipient_not_in_offer")
        if (
            not 4 <= len(result["body"].strip().splitlines()) <= 8
            or not result["subject"].strip()
        ):
            raise ConnectorError("mail_invalid")
        return {
            **result,
            "attachments": [state["cv"], state.get("letter") or self.letter(state)],
        }
