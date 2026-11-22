"""Parcours liste → fiche → liste sur les données synthétiques de web_offers.py."""

import os
import sys
from pathlib import Path

import psycopg
from linkedin_discovery.dashboard import ASSETS, app
from starlette.testclient import TestClient
from web_offers import Links


def hrefs(response):
    links = Links()
    links.feed(response.text)
    return links.hrefs


def main(work):
    with psycopg.connect() as db:
        db.execute("""
            INSERT INTO discovery.versions(id,offer_key,content)
            VALUES ('previous','cle-26','{"title":"Poste 26 ancien","description":"Version originale"}');
            INSERT INTO discovery.occurrences(cycle_id,profile,raw_hash,raw,version_id,observed_at)
            VALUES ('A','ancien','previous','{}','previous','2026-09-01');
            UPDATE discovery.occurrences SET missions='Analyser les relevés', raw=
               '{"salary":"100","sector":"Atelier","description":"Source <script>injection()</script>"}'
            WHERE version_id='26';
            INSERT INTO documents.cv_versions(sha256,pdf,markdown,provenance)
               SELECT encode(sha256(b),'hex'),b,'Synthétique','fixture' FROM (VALUES ('%PDF A'::bytea)) x(b);
            INSERT INTO discovery.cycles SELECT 'A','2026-09-01',sha256,'cv','p','p','{}','done'
            FROM documents.cv_versions;
            INSERT INTO discovery.qualifications(id,version_id,cv_hash,prompt_hash,status,result)
               SELECT 'q','26',sha256,'p','done','{"verdict":"retenir"}' FROM documents.cv_versions;
            INSERT INTO discovery.cycle_items VALUES ('A','26','q');
            INSERT INTO discovery.attempts(qualification_id,number,status,started_at,finished_at)
               VALUES ('q',1,'done','2026-10-01','2026-10-01');
            INSERT INTO applications.lots(candidate,cycle_id,mode) VALUES ('test','A','production');
            INSERT INTO applications.dossiers(id,candidate,identity,mode,cycle_id,version_id,canonical_url,
                content,cv_sha256,uncertain)
            SELECT '00000000-0000-0000-0000-000000000001','test','cle-26','production','A','previous',
                'https://example.invalid','{}',sha256,false FROM documents.cv_versions;
            INSERT INTO applications.lot_dossiers SELECT l.id,d.id,1 FROM applications.lots l,applications.dossiers d;
            INSERT INTO applications.submission_attempts(id,dossier_id,generation,version_id,cv_sha256,lease_until,status,outcome)
            SELECT '00000000-0000-0000-0000-000000000002',id,1,version_id,cv_sha256,now(),'no_submission',
                '{"status":"waiting","question":{"kind":"challenge","text":"secret-prive"}}' FROM applications.dossiers;
            INSERT INTO applications.submission_attempts(id,dossier_id,generation,version_id,cv_sha256,lease_until,status)
            SELECT '00000000-0000-0000-0000-000000000003',id,2,version_id,cv_sha256,now(),'transmitting'
            FROM applications.dossiers;
        """)
    os.environ["DASHBOARD_POSTGRES_DSN"] = "user=web_recette"
    path = "/dashboard/offres?q=Poste&tri=poste&page=2"
    with TestClient(app, base_url="http://localhost") as client:
        page = client.get(path)
        link = next(h for h in hrefs(page) if h.startswith("/dashboard/offres/"))
        before = client.get(link)
        assert before.status_code == 200
        assert (
            "Dépôt à vérifier" in before.text
            and "Vérification humaine demandée" in before.text
        )
        assert path in hrefs(before) and client.get(path).text == page.text
        assert client.get(link.split("?")[0]).status_code == 200
        assert client.get("/dashboard/offres/unknown").status_code == 404
        assert client.get("/dashboard/offres/" + "a" * 64).status_code == 404
        assert (
            client.get(link, headers={"Origin": "https://example.invalid"}).status_code
            == 403
        )

        with psycopg.connect() as db:
            db.execute("""UPDATE applications.submission_attempts SET status='confirmed' WHERE generation=2;
                INSERT INTO applications.submission_receipts(dossier_id,attempt_id,evidence)
                SELECT dossier_id,id,'{"message":"secret-prive","url":"https://portail.example.invalid/recu?token=secret-prive"}' FROM applications.submission_attempts WHERE generation=2""")
        html = client.get(link).text
        for expected in (
            "Poste 26",
            "Analyser les relevés",
            "Atelier",
            "Version examinée pour le dossier",
            "previous",
            "Dépôt confirmé",
            "Reçu de dépôt",
            "Empreinte SHA-256",
            "portail.example.invalid",
            "Vérification humaine demandée",
            "Qualification",
            "Entrée dans le lot",
            "Tentative de dépôt",
            "Reçu enregistré",
        ):
            assert expected in html, expected
        assert "Dépôt confirmé" in client.get(path).text and path in hrefs(
            client.get(link)
        )
        assert "secret-prive" not in html and "<script>injection()" not in html
        html = html.replace(
            '<link rel="stylesheet" href="/dashboard/assets/css">',
            "<style>" + ASSETS.joinpath("dashboard.css").read_text() + "</style>",
        )
        script = """<script>
            const panel=document.querySelector('.decision'), copy=document.querySelector('.job-copy');
            document.querySelector('.observation summary').click();
            if(innerWidth<=640 && document.documentElement.scrollWidth<=innerWidth &&
               panel.getBoundingClientRect().top<copy.getBoundingClientRect().top &&
               document.querySelector('.observation').open && document.querySelector('.return').href.includes('page=2'))
               document.documentElement.dataset.detail='ok';
        </script>"""
        (work / "detail.html").write_text(html.replace("</main>", "</main>" + script))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
