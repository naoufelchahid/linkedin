"""Recette de la route Starlette et des privilèges avec la même liste synthétique."""

import os
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from linkedin_discovery.dashboard import ASSETS, app
from starlette.testclient import TestClient


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.append(dict(attrs)["href"])


def main(work):
    with psycopg.connect() as db:
        db.execute("""INSERT INTO discovery.versions(id, offer_key, content)
            SELECT n::text, 'cle-'||n,
                jsonb_build_object('title', 'Poste '||lpad(n::text,2,'0'),
                  'company', CASE WHEN n < 4 THEN 'Alpha' ELSE 'Beta' END,
                  'location', 'Rabat') FROM generate_series(1,31) n""")
        db.execute("""INSERT INTO discovery.occurrences
            (cycle_id,profile,raw_hash,raw,version_id,observed_at,contract_type)
            SELECT 'A','test',id,'{}',id,'2026-10-01','CDI' FROM discovery.versions""")
        db.execute("""INSERT INTO discovery.occurrences
            (cycle_id,profile,raw_hash,raw,version_id,observed_at,contract_type)
            VALUES ('B','test','1','{}','1','2026-11-01','CDD')""")
        db.execute("CREATE ROLE web_recette LOGIN IN ROLE linkedin_web")
        db.execute("SET LOCAL ROLE web_recette")
        for privilege, relation in [
            ("SELECT", "documents.cv_versions"),
            ("SELECT", "applications.dossiers"),
            ("UPDATE", "api.offres_web_v1"),
        ]:
            assert not db.execute(
                "SELECT has_table_privilege(current_user, %s::oid, %s)",
                (
                    db.execute(
                        "SELECT oid FROM pg_class WHERE relname=%s",
                        (relation.split(".")[1],),
                    ).fetchone()[0],
                    privilege,
                ),
            ).fetchone()[0]
    # Le compte jetable a uniquement le rôle de lecture, même avant SET LOCAL ROLE.
    with psycopg.connect() as db:
        from psycopg import sql

        db.execute(
            sql.SQL("ALTER ROLE web_recette PASSWORD {}").format(
                sql.Literal(os.environ["PGPASSWORD"])
            )
        )
    os.environ["DASHBOARD_POSTGRES_DSN"] = "user=web_recette"
    with TestClient(app, base_url="http://localhost") as client:
        path = "/dashboard/offres"
        desktop = client.get(path, params={"tri": "poste"})
        assert desktop.status_code == 200 and "31 offres" in desktop.text
        assert "Poste 25" in desktop.text and "Poste 26" not in desktop.text
        links = Links()
        links.feed(desktop.text)
        following = next(url for url in links.hrefs if "page=2" in url)
        assert "tri=poste" in following and urlsplit(following).path == path
        second = client.get(following)
        assert "Poste 26" in second.text and "Poste 01" not in second.text
        filters = {
            "q": "ALPha",
            "cycle": "A",
            "du": "2026-10-01",
            "au": "2026-10-01",
            "entreprise": "Alpha",
            "lieu": "Rabat",
            "contrat": "CDI",
            "verdict": "en attente",
            "etat": "sans dossier",
            "tri": "entreprise",
        }
        assert "3 offres" in client.get(path, params=filters).text
        assert "Aucune offre" in client.get(path, params={**filters, "q": "%"}).text
        assert "Aucune offre" in client.get(path, params={"au": "2026-01-01"}).text
        assert "1 offre<" in client.get(path, params={"contrat": "CDD"}).text
        for params in ({"tri": "inconnu"}, {"page": "0"}, {"du": "x"}):
            assert client.get(path, params=params).status_code == 400
        assert (
            client.get(path, headers={"Origin": "https://example.invalid"}).status_code
            == 403
        )
        # Chrome applique réellement les media queries sur le HTML et le CSS servis.
        html = desktop.text.replace(
            '<link rel="stylesheet" href="/dashboard/assets/css">',
            "<style>" + ASSETS.joinpath("dashboard.css").read_text() + "</style>",
        )
        script = """<script>
          const row = document.querySelector('#rows tbody tr');
          if (innerWidth <= 640 && getComputedStyle(row).display === 'grid'
              && document.documentElement.scrollWidth <= innerWidth
              && row.innerText.includes('Alpha') && row.innerText.includes('Sans dossier'))
              document.documentElement.dataset.mobile = 'ok';
          </script>"""
        (work / "mobile.html").write_text(html.replace("</main>", "</main>" + script))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
