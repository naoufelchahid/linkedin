"""Fiche de suivi en lecture seule. Les identifiants de navigation désignent une offre."""

import re
from html import escape
from urllib.parse import urlencode

from starlette.responses import HTMLResponse, PlainTextResponse

from .web_offers import PATH, STATES, VERDICTS

ACTIONS = {
    "sans dossier": "Consulter la qualification.",
    "dossier ouvert": "Poursuivre la préparation du dossier.",
    "dépôt à vérifier": "Vérifier le résultat sur le portail.",
    "bloquée": "Examiner le blocage avant de reprendre.",
    "en attente": "Consulter la demande en attente.",
    "dépôt confirmé": "Consulter le reçu du dépôt.",
}
EVENTS = {
    "collecte": "Collecte",
    "qualification": "Qualification",
    "revue": "Revue du candidat",
    "lot": "Entrée dans le lot",
    "tentative": "Tentative de dépôt",
    "confirmation": "Reçu enregistré",
}


def value(item):
    return escape(str(item)) if item not in (None, "") else "Non renseigné"


def facts(pairs):
    return (
        '<dl class="facts">'
        + "".join(f"<div><dt>{key}</dt><dd>{value(item)}</dd></div>" for key, item in pairs)
        + "</dl>"
    )


def stamp(instant):
    return instant.strftime("%d/%m/%Y %H:%M UTC")


def detail(db, params, offer_id):
    missing = PlainTextResponse("Offre introuvable.", status_code=404)
    if not re.fullmatch(r"[0-9a-f]{64}", offer_id):
        return missing
    row = db.execute(
        """SELECT o.*,s.dossier_version,s.receipt_at,s.receipt_sha256,s.receipt_host,s.attempt_id,s.last_obstacle
           FROM api.offres_web_v1 o LEFT JOIN api.suivi_offres_v1 s USING(identity)
           WHERE o.offer_id=%s ORDER BY o.observed_at DESC,o.cycle_id DESC,o.version_id LIMIT 1""",
        (offer_id,),
    ).fetchone()
    if not row:
        return missing
    sources = db.execute(
        """SELECT * FROM api.sources_offres_v1 WHERE offer_id=%s
           ORDER BY observed_at DESC,cycle_id DESC,version_id,profile,raw_hash""",
        (offer_id,),
    ).fetchall()
    history = db.execute(
        """SELECT * FROM api.chronologie_offres_v1 WHERE offer_id=%s
           ORDER BY at DESC,kind,version_id,context""",
        (offer_id,),
    ).fetchall()
    src = sources[0]
    back = PATH + ("?" + escape(urlencode(params)) if params else "")
    url = row["canonical_url"] or ""
    external = (
        f'<a class="source-link" href="{escape(url)}">Ouvrir l’annonce</a>'
        if url.lower().startswith(("http://", "https://"))
        else ""
    )
    state = row["state"]
    obstacle = row["last_obstacle"] or (
        "Issue du dépôt inconnue" if state == "dépôt à vérifier" else "Aucun obstacle consigné"
    )
    progress = facts(
        [
            ("État courant", STATES[state]),
            ("Dernière activité", stamp(row["activity"])),
            ("Dernier obstacle consigné", obstacle),
            ("Prochaine action", ACTIONS[state]),
            ("Verdict applicable", VERDICTS.get(row["verdict"], row["verdict"])),
            ("Dernière version collectée", row["version_id"]),
            ("Version examinée pour le dossier", row["dossier_version"] or "Aucun dossier"),
        ]
    )
    receipt = ""
    if row["receipt_at"]:
        receipt = "<h3>Reçu de dépôt</h3>" + facts(
            [
                ("Observé le", stamp(row["receipt_at"])),
                ("Tentative confirmée", row["attempt_id"]),
                ("Portail", row["receipt_host"]),
                ("Empreinte SHA-256 de la preuve", row["receipt_sha256"]),
            ]
        )
    archive = "".join(
        f'<details class="observation"><summary>{value(s["profile"])} · {stamp(s["observed_at"])} · Version {value(s["version_id"])}</summary><div class="prose">{value(s["source_text"])}</div></details>'
        for s in sources
    )
    timeline = "".join(
        f"<li><time>{stamp(e['at'])}</time> · {EVENTS[e['kind']]} · {value(e['context'])} <small>(version {value(e['version_id'])})</small></li>"
        for e in history
    )
    conditions = facts(
        [
            ("Contrat", row["contract_type"]),
            ("Expérience", src["experience"]),
            ("Rémunération", src["salary"]),
        ]
    )
    work = facts(
        [
            ("Lieu", row["location"]),
            ("Modalité", src["work_mode"]),
            ("Activité", src["work_type"]),
            ("Secteur", src["sector"]),
        ]
    )
    title = value(row["title"])
    html = f"""<!doctype html><html lang="fr"><meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>{title} · Découverte</title><link rel="stylesheet" href="/dashboard/assets/css">
      <header><strong>Découverte</strong><nav><a href="{back}">Offres</a></nav></header>
      <main class="offer-detail"><a class="return" href="{back}">← Retour à la liste</a>
      <div class="job-head"><div><h1>{title}</h1><p class="byline">{value(row["company"])} · {value(row["location"])} · {value(row["contract_type"])}</p>
      <p>Publication · {value(src["posted_at"])}</p></div>{external}</div>
      <div class="job-layout"><section class="job-copy"><h2>Missions</h2><p class="prose">{value(src["missions"])}</p>
      <h2>Conditions</h2>{conditions}<h2>Modalités de travail</h2>{work}</section>
      <aside class="decision"><h2>Avancement</h2>{progress}{receipt}</aside></div>
      <section><h2>Chronologie</h2><ol>{timeline}</ol></section>
      <section class="sources"><h2>Versions et textes sources Apify</h2>{archive}</section></main></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
