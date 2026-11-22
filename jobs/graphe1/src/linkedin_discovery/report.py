"""Rapports locaux autonomes, privés et immuables ; aucune ressource distante."""

import json
import os
import tempfile
import uuid
from html import escape
from uuid import UUID

from .model import canonical_url, digest, dump, now, rank


def sample(items):
    eligible = sorted([i for i in items if i["status"] == "done"], key=lambda i: rank(i["offer"]))
    categories = [[], [], []]
    for item in eligible:
        result = item["result"]
        category = 2 if result["verdict"] == "écarter" else 1 if result["incertitude"] else 0
        categories[category].append(item)
    selected = [item for category in categories for item in category[:5]]
    selected_ids = {i["version_id"] for i in selected}
    selected.extend(i for i in eligible if i["version_id"] not in selected_ids)
    return selected[:15]


def local_report(store, report_id, html, sha256):
    if UUID(report_id).hex != report_id or digest(html) != sha256:
        raise ValueError("report_integrity_failed")
    directory = store.data / "reports"
    directory.mkdir(exist_ok=True, mode=0o700)
    path = directory / (report_id + ".html")
    if not path.exists():
        with tempfile.NamedTemporaryFile(dir=directory) as stream:
            stream.write(html.encode("utf-8"))
            stream.flush()
            try:
                os.link(stream.name, path)
            except FileExistsError:
                pass
    if digest(path.read_bytes()) != sha256:
        raise ValueError("report_integrity_failed")
    return path


def restore_report(store, cycle_id, report_id):
    row = store.db.execute(
        "SELECT snapshot, sha256 FROM reports WHERE cycle_id=? AND id=?", (cycle_id, report_id)
    ).fetchone()
    if row:
        html = render_report(json.loads(row["snapshot"]))
        return local_report(store, report_id, html, row["sha256"])
    return None


def make_report(store, cycle_id, report_id=None):
    if report_id is not None:
        if UUID(report_id).hex != report_id:
            raise ValueError("invalid_report_id")
        existing = restore_report(store, cycle_id, report_id)
        if existing is not None:
            return report_id, existing
    cycle = store.cycle(cycle_id)
    items = store.items(cycle_id)
    selected = sample(items)
    source = cycle
    visited = {cycle_id}
    while json.loads(source["settings"]).get("replay_of"):
        source_id = json.loads(source["settings"])["replay_of"]
        if source_id in visited:
            raise ValueError("replay_source_cycle_invalid")
        visited.add(source_id)
        source = store.cycle(source_id)
    runs = [
        dict(row)
        for row in store.db.execute(
            "SELECT profile,run_id,status,error FROM runs WHERE cycle_id=? ORDER BY profile",
            (source["id"],),
        )
    ]
    errors = [
        dict(row)
        for row in store.db.execute(
            "SELECT profile,error,count(*) total FROM occurrences WHERE cycle_id=? AND error<>'' GROUP BY profile,error",
            (cycle_id,),
        )
    ]
    report_id = report_id or uuid.uuid4().hex
    snapshot = dict(
        id=report_id,
        cycle_id=cycle_id,
        created_at=now(),
        source_cycle_id=source["id"],
        source_status=source["status"],
        cv_hash=cycle["cv_hash"],
        prompt_hash=cycle["prompt_hash"],
        status=cycle["status"],
        runs=runs,
        ingestion_errors=errors,
        selected=selected,
        qualification_errors=[i for i in items if i["status"] != "done"],
        totals=dict(
            annonces=len(items),
            qualifiees=sum(i["status"] == "done" for i in items),
            retenues=sum(i["effective_verdict"] == "retenir" for i in items),
            erreurs=sum(i["status"] != "done" for i in items),
        ),
    )

    html = render_report(snapshot)
    sha256 = digest(html)
    path = store.data / "reports" / (report_id + ".html")
    with store.transaction():
        store.db.execute(
            "INSERT INTO reports VALUES(?,?,?,?,?,?)",
            (report_id, cycle_id, snapshot["created_at"], dump(snapshot), str(path), sha256),
        )
        store.db.executemany(
            "INSERT INTO review_items VALUES(?,?,?,?)",
            [
                (report_id, n, i["version_id"], i["qualification_id"])
                for n, i in enumerate(selected, 1)
            ],
        )
    return report_id, local_report(store, report_id, html, sha256)


def render_report(snapshot):
    report_id = snapshot["id"]
    selected = snapshot["selected"]

    def e(value):
        return escape(str(value), quote=True)

    cards = []
    for number, item in enumerate(selected, 1):
        offer, result = item["offer"], item["result"]
        url = canonical_url(offer["url"])
        link = (
            f'<a href="{e(url)}" rel="noreferrer noopener" target="_blank">Ouvrir l’annonce</a>'
            if url
            else "Lien indisponible"
        )
        cards.append(f"""<article><h2>#{number} · {e(offer["title"])}</h2>
<p>{e(offer["company"])} · {e(offer["location"])} · {e(offer["work_mode"])} · {e(offer["posted_at"])}</p>
<p>{link}</p><p><strong>Codex : {e(result["verdict"])}</strong> · Incertitude : {"oui" if result["incertitude"] else "non"}</p>
<p>{e(result["motif"])}</p><h3>Mission citée</h3><blockquote>{e(result["mission_citee"] or "Non établie")}</blockquote>
<h3>Compétence citée dans le CV</h3><blockquote>{e(result["competence_cv"] or "Non établie")}</blockquote>
<details><summary>Texte de l’annonce sauvegardé</summary><p>{e(offer["description"])}</p></details>
<p><strong>Ton verdict enregistré :</strong> {e(item["human_verdict"] or "À renseigner dans la conversation")}</p>
<p>Répondre : rapport {e(report_id)}, annonce #{number}, retenir ou écarter.</p></article>""")
    issues = "".join(
        f"<li>{e(r['profile'])} : {e(r['status'])} {e(r['error'])}</li>" for r in snapshot["runs"]
    )
    data_issues = "".join(
        f"<li>{e(i['offer']['title'])} : {e(i['status'])} {e(i['error'])}</li>"
        for i in snapshot["qualification_errors"]
    )
    ingestion_issues = "".join(
        f"<li>{e(r['profile'])} : {e(r['error'])} ({r['total']})</li>"
        for r in snapshot["ingestion_errors"]
    )
    totals = snapshot["totals"]
    return f"""<!doctype html><html lang="fr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Revue du pilote · {e(report_id[:8])}</title>
<style>body{{font:17px/1.55 system-ui;margin:40px auto;padding:0 20px;max-width:960px;color:#17223b;background:#f4f6fa}}article,header{{background:white;border:1px solid #d8dfe9;border-radius:12px;padding:24px;margin:20px 0}}h1,h2{{line-height:1.2}}h3{{font-size:1em}}a{{color:#174fba}}blockquote{{margin-left:0;border-left:3px solid #536eab;padding-left:16px}}p{{overflow-wrap:anywhere}}details p{{white-space:pre-wrap}}</style>
<header><h1>Revue du pilote de qualification</h1><p>Rapport privé figé : {e(report_id)}</p>
<p>Cycle de qualification : {e(snapshot["cycle_id"])} · État : {e(snapshot["status"])}</p>
<p>Collecte source : {e(snapshot["source_cycle_id"])} · État : {e(snapshot["source_status"])}</p>
<p>{totals["annonces"]} annonces · {totals["qualifiees"]} qualifiées · {totals["retenues"]} retenues · {totals["erreurs"]} problèmes de qualification</p>
<p>Échantillon : {len(selected)} annonces, cible 5 retenues sans incertitude, 5 avec incertitude, 5 écartées selon disponibilité.</p>
<p>Les prérequis sont ignorés. Les missions imprécises sont acceptées avec incertitude.</p>
<details><summary>Bilan de collecte et problèmes</summary><ul>{issues}{data_issues}{ingestion_issues}</ul></details></header>
{"".join(cards) if cards else "<p>Aucune annonce qualifiée disponible pour la revue.</p>"}</html>"""
