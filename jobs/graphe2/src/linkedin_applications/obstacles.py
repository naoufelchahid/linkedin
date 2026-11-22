"""Observations techniques autorisées dans la matrice privée des blocages."""

import re
from urllib.parse import urlsplit

# Chaque signal a un sens précis et une condition positive de reprise.
SIGNALS = {
    "permission_refusee": (
        "permission_locale",
        "Action refusée par le connecteur local.",
        "La permission nécessaire est visible comme accordée.",
    ),
    "session_expiree": (
        "session_expiree",
        "Le portail demande une nouvelle connexion.",
        "La session authentifiée du bon compte est visible.",
    ),
    "champ_indisponible": (
        "champ_indisponible",
        "Le champ attendu est absent ou désactivé.",
        "Le champ requis est visible et disponible.",
    ),
    "piece_incomplete": (
        "piece_incomplete",
        "La référence ou la pièce attendue manque dans son champ.",
        "La pièce exacte est observable dans son champ.",
    ),
    "limitation_debit": (
        "limitation_debit",
        "Le portail indique une limitation de débit.",
        "Le portail indique explicitement que la limitation est levée.",
    ),
    "verification_humaine": (
        "verification_humaine",
        "Le portail demande une vérification humaine.",
        "Le portail indique que la vérification humaine a abouti.",
    ),
    "http_403_apres_validation": (
        "inconnue",
        "HTTP 403 après validation.",
        "Un reçu attribuable au dossier est visible.",
    ),
    "blocage_indetermine": (
        "inconnue",
        "Obstacle sans cause établie.",
        "Le prérequis auparavant bloquant est positivement observé.",
    ),
}
STAGES = ("ouverture", "connexion", "formulaire", "piece", "validation", "confirmation")


def describe(result, state):
    signal = result.get("signal")
    if signal not in SIGNALS:
        if result.get("kind") != "blocked":
            return None
        signal = "blocage_indetermine"
    stage = result.get("stage")
    if stage not in STAGES:
        stage = "formulaire"
    transmitted = bool(result.get("transmission_attempted")) or result.get("kind") in {
        "submitted",
        "unknown",
    }
    if signal == "http_403_apres_validation":
        stage, transmitted = "validation", True
    try:
        url = urlsplit(result.get("portal_origin") or state["offer"].get("url", ""))
        host = url.hostname if url.scheme == "https" else None
    except ValueError:
        host = None
    if host and not re.fullmatch(r"[a-z0-9.-]{1,253}", host):
        host = None
    cause, observation, condition = SIGNALS[signal]
    return {
        "signal": signal,
        "stage": stage,
        "portal": host,
        "cause": cause,
        "observation": observation,
        "condition": condition,
        "transmission_attempted": transmitted,
    }
