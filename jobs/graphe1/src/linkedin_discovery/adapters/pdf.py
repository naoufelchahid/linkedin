"""Extraction du CV dans l’ordre de lecture du PDF."""

import subprocess
from pathlib import Path

from ..errors import ConnectorError


def read_cv(path):
    if path is None:
        raise ConnectorError("cv_not_configured")
    try:
        content = Path(path).read_bytes()
        if not content.startswith(b"%PDF"):
            raise ConnectorError("cv_not_pdf")
        # L'ordre de lecture sépare les colonnes ; -layout entrelace le bandeau
        # latéral et l'expérience et rend des citations fidèles non contiguës.
        process = subprocess.run(
            ["pdftotext", "-", "-"], input=content, capture_output=True, timeout=30
        )
        text = process.stdout.decode("utf-8", errors="replace").strip()
        if process.returncode or not text:
            raise ConnectorError("cv_text_unreadable")
        return content, text
    except FileNotFoundError:
        raise ConnectorError("cv_or_pdftotext_missing") from None
    except (OSError, subprocess.TimeoutExpired):
        raise ConnectorError("cv_read_failed") from None
