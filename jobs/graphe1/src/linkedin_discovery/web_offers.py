"""Liste des offres collectées, rendue côté serveur depuis le contrat SQL web."""

import os
from datetime import date
from html import escape
from urllib.parse import urlencode

import psycopg
from psycopg.rows import dict_row
from starlette.responses import HTMLResponse, PlainTextResponse

SORTS = {
    "activite": ("activity DESC", "Activité récente"),
    "poste": ("lower(title) ASC NULLS LAST", "Poste (A–Z)"),
    "entreprise": ("lower(company) ASC NULLS LAST", "Entreprise (A–Z)"),
}
VERDICTS = {
    "retenir": "Retenue",
    "écarter": "Écartée",
    "en attente": "En attente de qualification",
    "erreur": "Erreur technique",
}
STATES = {
    s: s.capitalize()
    for s in (
        "sans dossier",
        "dossier ouvert",
        "reprise suspendue",
        "confirmation en attente",
        "réponse en attente",
        "suivi à approuver",
        "suivi approuvé",
        "suivi à vérifier",
        "suivi envoyé",
        "bloquée",
        "en attente",
        "dépôt à vérifier",
        "dépôt confirmé",
    )
}
PAGE_SIZE = 25
PATH = "/dashboard/offres"


DEPOSITS = {
    "confirmé": "Dépôt confirmé",
    "à vérifier": "Dépôt à vérifier",
    "bloqué": "Bloquée après échec",
    "autres": "Autres offres non postulées",
}
SCOPE_FIELDS = {
    "cycle": "Cycle",
    "du": "Collectée du",
    "au": "Au",
    "entreprise": "Entreprise",
    "lieu": "Lieu",
    "contrat": "Contrat",
}


def filtered_offers(params):
    scopes, scope_values = [], []
    for name, column in (("cycle", "cycle_id"), ("du", "observed_at"), ("au", "observed_at")):
        if value := params.get(name):
            if name == "cycle":
                scopes.append("cycle_id = %s")
                scope_values.append(value)
            else:
                day = date.fromisoformat(value)
                scopes.append(column + (" >= %s::date" if name == "du" else " < %s::date + 1"))
                scope_values.append(day)
    if params.get("du") and params.get("au") and params["du"] > params["au"]:
        raise ValueError
    # Le dernier état vaut pour l’identité. Le cycle et la période sélectionnent
    # l’occurrence affichée. Les filtres métier portent sur cette ligne unique.
    conditions, values = [], []
    if term := params.get("q", "").strip():
        conditions.append(
            "(strpos(lower(title), lower(%s)) > 0 OR strpos(lower(company), lower(%s)) > 0)"
        )
        values.extend([term, term])
    for key, column in (
        ("entreprise", "company"),
        ("lieu", "location"),
        ("contrat", "contract_type"),
        ("verdict", "verdict"),
        ("etat", "state"),
    ):
        if value := params.get(key):
            conditions.append(column + " = %s")
            values.append(value)
    if category := params.get("depot"):
        if category == "non postulées":
            conditions.append("deposit IN ('bloqué','autres')")
        elif category in DEPOSITS:
            conditions.append("deposit = %s")
            values.append(category)
        else:
            raise ValueError
        conditions.append("verdict = 'retenir'")
    if week := params.get("semaine"):
        conditions.append("date_trunc('week',receipt_at)::date = %s")
        values.append(date.fromisoformat(week))
    scope = " AND ".join(scopes) or "true"
    where = " AND ".join(conditions) or "true"
    source = f"""WITH latest AS (SELECT DISTINCT ON (identity) * FROM api.offres_web_v1
                   WHERE {scope} ORDER BY identity, observed_at DESC, cycle_id DESC, version_id)
                 SELECT * FROM (SELECT latest.*, suivi.receipt_at, suivi.activity AS state_since,
                    coalesce(suivi.deposit,'autres') AS deposit
                    FROM latest LEFT JOIN api.suivi_offres_v1 suivi USING(identity)) classified
                 WHERE {where}"""
    return source, scope_values + values


def query_offers(db, params):
    page = int(params.get("page", 1))
    sort = params.get("tri", "activite")
    if not 1 <= page <= 2_147_483_647 or sort not in SORTS:
        raise ValueError
    source, bindings = filtered_offers(params)
    total = db.execute(f"SELECT count(*) AS n FROM ({source}) filtered", bindings).fetchone()["n"]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages)
    order = SORTS[sort][0]
    rows = db.execute(
        f"{source} ORDER BY {order}, identity LIMIT %s OFFSET %s",
        [*bindings, PAGE_SIZE, (page - 1) * PAGE_SIZE],
    ).fetchall()
    return rows, total, page, pages


def render_offers(params, rows, total, page, pages):
    def label(value):
        return escape(value or "—")

    def field(key, name, kind="text"):
        value = escape(params.get(key, ""), quote=True)
        return f'<label>{name}<input type="{kind}" name="{key}" value="{value}"></label>'

    def select(key, name, options, default=""):
        parts = []
        for value, title in options.items():
            selected = " selected" if value == params.get(key, default) else ""
            parts.append(f'<option value="{escape(value)}"{selected}>{escape(title)}</option>')
        return f'<label>{name}<select name="{key}">{"".join(parts)}</select></label>'

    def page_link(position, title):
        query = urlencode({**params, "page": position})
        return f'<a href="{PATH}?{escape(query)}">{title}</a>'

    fields = "".join(
        [
            field("q", "Poste ou entreprise", "search"),
            field("cycle", "Cycle"),
            field("du", "Collectée du", "date"),
            field("au", "Au", "date"),
            field("entreprise", "Entreprise"),
            field("lieu", "Lieu"),
            field("contrat", "Contrat"),
            select("verdict", "Verdict", {"": "Tous", **VERDICTS}),
            select("etat", "État de candidature", {"": "Tous", **STATES}),
            select("tri", "Tri", {k: v[1] for k, v in SORTS.items()}, "activite"),
        ]
    )
    if params.get("depot"):
        fields += select(
            "depot",
            "Dépôt des offres retenues",
            {"": "Tous", **DEPOSITS, "non postulées": "Non postulées"},
        )
    if params.get("semaine"):
        fields += field("semaine", "Semaine de confirmation (lundi)", "date")
    dashboard_url = "/dashboard?" + escape(
        urlencode({k: params[k] for k in SCOPE_FIELDS if params.get(k)})
    )
    body = []
    for row in rows:
        title = label(row["title"])
        suffix = "?" + escape(urlencode(params)) if params else ""
        title = f'<a href="{PATH}/{row["offer_id"]}{suffix}">{title}</a>'
        activity = row["activity"].strftime("%d/%m/%Y %H:%M")
        body.append(f"""<tr><td><strong>{title}</strong><small>{label(row["company"])}</small></td>
            <td>{label(row["location"])}<small>{label(row["contract_type"])}</small></td>
            <td>{label(VERDICTS.get(row["verdict"], row["verdict"]))}</td>
            <td>{label(STATES.get(row["state"], row["state"]))}</td><td>{activity}</td></tr>""")
    nav = [f"<span>Page {page} sur {pages}</span>"]
    if page > 1:
        nav.insert(0, page_link(page - 1, "Précédente"))
    if page < pages:
        nav.append(page_link(page + 1, "Suivante"))
    listing = (
        f"""<div id="rows"><div class="scroll"><table><thead><tr>
      <th>Poste et entreprise</th><th>Lieu et contrat</th><th>Verdict</th>
      <th>État de candidature</th><th>Dernière activité</th></tr></thead>
      <tbody>{"".join(body)}</tbody></table></div></div>
      <nav class="pages" aria-label="Pagination">{" ".join(nav)}</nav>"""
        if rows
        else ""
    )
    return f"""<!doctype html><html lang="fr"><meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Offres · Découverte</title><link rel="stylesheet" href="/dashboard/assets/css">
      <header><strong>Découverte</strong><nav aria-label="Navigation principale">
      <a href="{PATH}" aria-current="page">Offres</a><a href="{dashboard_url}#metrics">Vue d’ensemble</a>
      <a href="/dashboard/decouverte#lancer">Lancer une découverte</a></nav></header>
      <main><h1>Offres</h1><form action="{PATH}" method="get" class="tools">{fields}
      <button class="primary">Appliquer</button><a href="{PATH}">Réinitialiser</a></form>
      <p id="count">{(str(total) + (" offre" if total == 1 else " offres")) if total else "Aucune offre"}</p>
      {listing}</main></html>"""


def offers(params, offer_id=None, *, overview=False):
    dsn = os.environ.get("DASHBOARD_POSTGRES_DSN")
    if not dsn:
        return PlainTextResponse("Connexion de lecture indisponible.", status_code=503)
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as db:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            db.execute("SET LOCAL ROLE linkedin_web")
            db.execute("SET LOCAL TIME ZONE 'UTC'")
            if overview:
                from .web_metrics import overview_page

                return overview_page(db, params)
            if offer_id is not None:
                from .web_offer_detail import detail

                return detail(db, params, offer_id)
            result = query_offers(db, params)
    except ValueError:
        return PlainTextResponse("Paramètres de recherche invalides.", status_code=400)
    except psycopg.Error:
        return PlainTextResponse("Lecture des offres indisponible.", status_code=503)
    return HTMLResponse(render_offers(params, *result), headers={"Cache-Control": "no-store"})
