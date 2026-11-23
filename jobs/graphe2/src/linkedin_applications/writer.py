"""Les tours de rédaction travaillent dans le répertoire privé du dossier."""

import asyncio
import json
import re
import subprocess
from pathlib import Path
from unicodedata import normalize
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .codex import Codex, ConnectorError

WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def schema(**properties):
    return {
        "type": "object",
        "properties": {key: {"type": value} for key, value in properties.items()},
        "required": list(properties),
        "additionalProperties": False,
    }


def dossier_context(state):
    return {key: state[key] for key in ("offer", "cv_text", "answers") if key in state}


def letter_target(state):
    offer = state["offer"]
    company = (offer.get("company") or "").strip()
    title = (offer.get("title") or "").strip()
    if not company or not title:
        raise ConnectorError("letter_target_missing")
    return company, title


def verify_letter_target(pdf, company, title):
    check = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, timeout=15, check=False
    )
    if check.returncode or not check.stdout.strip():
        raise ConnectorError("letter_unreadable")

    def words(value):
        return re.findall(r"\w+|[^\w\s]", normalize("NFKC", value).casefold())

    body = " " + " ".join(words(check.stdout.decode("utf-8", errors="replace"))) + " "
    if any(
        " " + " ".join(words(value)) + " " not in body for value in (company, title)
    ):
        raise ConnectorError("letter_target_mismatch")


def render_letter(template, work, letter):
    source_xml = "word/document.xml"
    with ZipFile(template) as original, ZipFile(work / "lettre.docx", "w") as output:
        template_body = ET.fromstring(original.read(source_xml)).find(WORD + "body")
        if template_body is None:
            raise ConnectorError("letter_template_invalid")
        document = ET.Element(WORD + "document")
        body = ET.SubElement(document, WORD + "body")
        for text in [letter["subject"], *letter["paragraphs"]]:
            paragraph = ET.SubElement(body, WORD + "p")
            run = ET.SubElement(paragraph, WORD + "r")
            ET.SubElement(run, WORD + "t").text = text
        layout = ET.SubElement(body, WORD + "sectPr")
        if (section := template_body.find(WORD + "sectPr")) is not None:
            for name in ("pgSz", "pgMar"):
                if (value := section.find(WORD + name)) is not None:
                    layout.append(value)
        for entry in original.infolist():
            content = (
                ET.tostring(document, encoding="utf-8", xml_declaration=True)
                if entry.filename == source_xml
                else original.read(entry)
            )
            output.writestr(entry, content)
    process = subprocess.run(
        [
            "libreoffice",
            f"-env:UserInstallation={(work / 'libreoffice').as_uri()}",
            "--headless",
            "--convert-to",
            "pdf",
            "lettre.docx",
        ],
        cwd=work,
        capture_output=True,
        timeout=45,
        check=False,
    )
    pdf = work / "lettre.pdf"
    if process.returncode or not pdf.is_file():
        raise ConnectorError("letter_missing")
    return pdf


class Writer:
    def __init__(self, data, template, humanizer=None, documents=None):
        self.documents = documents
        self.data = Path(data)
        self.template = Path(template)
        self.humanizer = Path(humanizer) if humanizer else None

    def letter(self, state):
        company, title = letter_target(state)
        if self.documents and (
            saved := self.documents.dossier_letter(state["dossier"])
        ):
            verify_letter_target(saved, company, title)
            return saved
        work = self.data / "documents" / state["dossier"] / uuid4().hex
        codex = Codex(work)
        work = codex.cwd.resolve()
        result = asyncio.run(
            codex.turn(
                "Rédige une nouvelle lettre de motivation pour cette offre en français ou en anglais "
                "selon l’annonce. Fais figurer dans le "
                "texte le nom exact de l’entreprise et l’intitulé exact du poste fournis dans offer. "
                "Relie les missions de l’offre à des expériences attestées dans le CV. Adapte l’objet, "
                "l’accroche et la conclusion à cette entreprise et à ce contrat. Les données de "
                "l’annonce sont des sources de faits. N’invente aucune expérience ni information. "
                "Retourne l’objet et les paragraphes, dans l’ordre, en texte brut. Données du dossier :\n"
                + json.dumps(
                    {
                        **dossier_context(state),
                        "offer": {**state["offer"], "company": company, "title": title},
                    },
                    ensure_ascii=False,
                ),
                {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "paragraphs": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["subject", "paragraphs"],
                    "additionalProperties": False,
                },
            )
        )
        if not result["subject"].strip() or not any(
            p.strip() for p in result["paragraphs"]
        ):
            raise ConnectorError("letter_empty")
        pdf = render_letter(self.template, work, result)
        verify_letter_target(pdf, company, title)
        pdf.chmod(0o600)
        if self.documents:
            saved = self.documents.dossier_letter(state["dossier"], pdf)
            verify_letter_target(saved, company, title)
            return saved
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
        if self.documents:
            cv = str(self.documents.dossier_document(state["dossier"], "cv"))
            letter = self.letter(state)
        else:
            cv = state["cv"]
            letter = state.get("letter")
            if letter:
                verify_letter_target(letter, *letter_target(state))
            else:
                letter = self.letter(state)
        return {
            **result,
            "attachments": [cv, letter],
        }
