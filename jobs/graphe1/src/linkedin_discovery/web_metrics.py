"""Indicateurs du périmètre de collecte et dernier état de chaque offre."""

from datetime import datetime, timezone
from html import escape
from math import cos, pi, sin
from urllib.parse import urlencode

from starlette.responses import HTMLResponse

from .web_offers import DEPOSITS, PATH, SCOPE_FIELDS, STATES, VERDICTS, filtered_offers

COLORS = ("#19634a", "#c78720", "#ad4052", "#62728e")


def metrics(db, params):
    source, values = filtered_offers(params)
    scope = f"WITH scoped AS ({source}) "
    rows = db.execute(
        scope
        + """SELECT verdict, deposit, count(*) AS n FROM scoped
                                 GROUP BY verdict, deposit""",
        values,
    ).fetchall()
    verdicts = dict.fromkeys(VERDICTS, 0)
    deposits = dict.fromkeys(DEPOSITS, 0)
    for row in rows:
        verdicts[row["verdict"]] += row["n"]
        if row["verdict"] == "retenir":
            deposits[row["deposit"]] += row["n"]
    weeks = db.execute(
        scope
        + """, counts AS (
        SELECT date_trunc('week',receipt_at) AS week, count(*) AS n FROM scoped
        WHERE verdict='retenir' AND receipt_at IS NOT NULL GROUP BY 1
    ) SELECT w::date AS week, coalesce(n,0) AS n FROM
        generate_series((SELECT min(week) FROM counts),(SELECT max(week) FROM counts),
                        interval '1 week') w LEFT JOIN counts ON counts.week=w ORDER BY w""",
        values,
    ).fetchall()
    attention = db.execute(
        scope
        + """SELECT offer_id,title,state,state_since FROM scoped
        WHERE verdict='retenir' AND state IN ('en attente','bloquée','dépôt à vérifier')
        ORDER BY state_since,identity LIMIT 8""",
        values,
    ).fetchall()
    return verdicts, deposits, weeks, attention


def url(params, **filters):
    return PATH + "?" + escape(urlencode({**params, **filters}))


def pie(title, counts, names, params, key):
    total = sum(counts.values())
    legend, sectors = [], []
    start = 0
    for (category, count), color in zip(counts.items(), COLORS, strict=True):
        href = url(params, **{key: category})
        pct = 100 * count / total if total else 0
        desc = f"{names[category]} · {count} sur {total} ({pct:.1f} %)"
        legend.append(
            f'<li><a data-count="{count}" href="{href}"><i style="background:{color}"></i>{desc}</a></li>'
        )
        if not count:
            continue
        if count == total:
            shape = '<circle cx="50" cy="50" r="46"/>'
        else:
            a, b = (2 * pi * x / total - pi / 2 for x in (start, start + count))
            shape = (
                f'<path d="M50 50 L{50 + 46 * cos(a):.4f} {50 + 46 * sin(a):.4f} '
                f'A46 46 0 {int(count * 2 > total)} 1 {50 + 46 * cos(b):.4f} {50 + 46 * sin(b):.4f} Z"/>'
            )
        sectors.append(
            f'<a href="{href}" aria-label="{desc}" fill="{color}"><title>{desc}</title>{shape}</a>'
        )
        start += count
    drawing = (
        f'<svg viewBox="0 0 100 100" role="group" aria-label="{title}">{"".join(sectors)}</svg>'
        if total
        else "<p>Aucune offre dans ce périmètre.</p>"
    )
    return f'<section><h2>{title}</h2><div class="pie">{drawing}<ul>{"".join(legend)}</ul></div></section>'


def trend(weeks, params):
    if not weeks:
        return "<p>Aucun dépôt confirmé sur les offres du périmètre.</p>"
    peak = max(w["n"] for w in weeks)
    points, dots, links = [], [], []
    for index, row in enumerate(weeks):
        x = 10 + 380 * index / max(1, len(weeks) - 1)
        y = 70 - 60 * row["n"] / peak
        points.append(f"{x:.2f},{y:.2f}")
        dots.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3"/>')
        week = row["week"].isoformat()
        href = url(params, depot="confirmé", semaine=week)
        links.append(
            f'<li><a data-count="{row["n"]}" href="{href}">Semaine du {week} · {row["n"]}</a></li>'
        )
    line = " ".join(points)
    return f'<svg class="trend" viewBox="0 0 400 80" aria-hidden="true"><polyline points="{line}"/>{"".join(dots)}</svg><ul>{"".join(links)}</ul>'


def overview_page(db, query):
    params = {k: query[k] for k in SCOPE_FIELDS if query.get(k)}
    verdicts, deposits, weeks, attention = metrics(db, params)
    fields = []
    for key, name in SCOPE_FIELDS.items():
        field_type = "date" if key in ("du", "au") else "text"
        fields.append(
            f'<label>{name}<input type="{field_type}" name="{key}" value="{escape(params.get(key, ""))}"></label>'
        )
    scope = (
        " · ".join(f"{SCOPE_FIELDS[k]} {escape(v)}" for k, v in params.items())
        or "Toutes les offres collectées"
    )
    cards = []
    for label, count, filters in (
        ("Offres collectées", sum(verdicts.values()), {}),
        ("Offres retenues", verdicts["retenir"], {"verdict": "retenir"}),
        ("Dépôts confirmés", deposits["confirmé"], {"depot": "confirmé"}),
        ("Dépôts à vérifier", deposits["à vérifier"], {"depot": "à vérifier"}),
    ):
        cards.append(
            f'<a data-count="{count}" href="{url(params, **filters)}"><strong>{count}</strong>{label}</a>'
        )
    tasks = []
    for row in attention:
        state = STATES[row["state"]]
        title = escape(row["title"] or "Offre")
        since = row["state_since"].strftime("%d/%m/%Y %H:%M UTC")
        href = PATH + "/" + row["offer_id"] + "?" + escape(urlencode(params))
        tasks.append(f'<li><a href="{href}">{title}</a> · {state} · {since}</li>')
    pending = deposits["bloqué"] + deposits["autres"]
    stamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    html = f"""<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <script>if (["offres", "fiche", "lancer"].includes(location.hash.slice(1).split("?")[0])) location.replace("/dashboard/decouverte"+location.hash);</script>
      <title>Suivi des offres</title><link rel="stylesheet" href="/dashboard/assets/css">
      <header><strong>Découverte</strong><nav><a href="{url(params)}">Offres</a><a href="/dashboard" aria-current="page">Vue d’ensemble</a>
      <a href="/dashboard/decouverte#lancer">Lancer une découverte</a></nav></header>
      <main class="overview"><h1>Suivi des offres</h1><form method="get" action="/dashboard" class="tools">{"".join(fields)}
      <button class="primary">Appliquer</button><a href="/dashboard">Réinitialiser</a></form>
      <p>{scope} · Actualisé le {stamp}</p><div class="metric-links">{"".join(cards)}</div>
      {pie("Qualification des offres collectées", verdicts, VERDICTS, params, "verdict")}
      {pie("Candidatures des offres retenues", deposits, DEPOSITS, params, "depot")}
      <a data-count="{pending}" href="{url(params, depot="non postulées")}">Non postulées · {pending} ({deposits["bloqué"]} bloquées et {deposits["autres"]} autres)</a>
      <section><h2>Dépôts par semaine de confirmation</h2>{trend(weeks, params)}</section>
      <section><h2>À traiter</h2>{"<ol>" + "".join(tasks) + "</ol>" if tasks else "<p>Aucun dossier à traiter.</p>"}</section></main></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
