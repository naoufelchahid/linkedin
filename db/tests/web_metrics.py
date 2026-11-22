"""Comparaison des agrégats SQL, des listes et de la fiche avec le même périmètre."""

import os
import subprocess
import sys
import threading
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import psycopg
from linkedin_discovery.dashboard import app
from starlette.testclient import TestClient


class Counters(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "data-count" in attrs:
            self.links.append((attrs["href"], int(attrs["data-count"])))


def check_counts(client, params, expected):
    response = client.get("/dashboard", params=params)
    assert response.status_code == 200
    links = Counters(response.text).links
    assert [n for _, n in links[:13]] == expected
    for href, n in links:
        query = parse_qs(urlsplit(href).query)
        assert all(query[k] == [v] for k, v in params.items())
        page = client.get(href)
        count = str(n) + (" offre" if n == 1 else " offres") if n else "Aucune offre"
        assert f'<p id="count">{count}</p>' in page.text
    return response.text


def mobile(client, work):
    # Le navigateur parcourt les véritables réponses ASGI avec un serveur loopback jetable.
    harness = """<meta name="viewport" content="width=device-width,initial-scale=1">
        <iframe style="border:0;width:100%;height:700px" src="/dashboard?cycle=A"></iframe>
        <script>
        const f=document.querySelector('iframe');let step=0,listing;
        f.onload=()=>{
            const d=f.contentDocument;
            if(step===0){
                const a=d.querySelectorAll('.pie svg a')[0];a.focus();
                if(d.activeElement!==a || d.documentElement.scrollWidth>f.clientWidth)return;
                step++; a.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:f.contentWindow}));
            }else if(step===1){
                listing=f.contentWindow.location.href;
                const a=d.querySelector('#rows tbody a');if(!a||!listing.includes('cycle=A'))return;
                step++; a.click();
            }else if(step===2){
                const a=d.querySelector('a.return');if(!a)return;step++;a.click();
            }else if(step===3 && f.contentWindow.location.href===listing)
                document.documentElement.dataset.metrics='ok';
        }</script>"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/recette":
                payload, code, mime = harness.encode(), 200, "text/html; charset=utf-8"
            elif self.path.startswith("/dashboard"):
                page = client.get(self.path)
                payload, code, mime = (
                    page.content,
                    page.status_code,
                    page.headers["content-type"],
                )
            else:
                payload, code, mime = b"", 404, "text/plain"
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.end_headers()
            self.wfile.write(payload)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            dom = subprocess.check_output(
                [
                    os.environ.get("CHROME", "google-chrome"),
                    "--headless",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-background-networking",
                    "--disable-dev-shm-usage",
                    f"--user-data-dir={work / 'metrics-profile'}",
                    "--window-size=390,844",
                    "--virtual-time-budget=10000",
                    "--dump-dom",
                    f"http://127.0.0.1:{server.server_port}/recette",
                ],
                stderr=subprocess.DEVNULL,
                timeout=40,
            )
            assert b'data-metrics="ok"' in dom
        finally:
            server.shutdown()
            thread.join()


def main(work):
    with psycopg.connect() as db:
        db.execute("""
            INSERT INTO discovery.cycles SELECT 'B',created_at,cv_hash,cv_text,prompt_hash,prompt,settings,status
              FROM discovery.cycles WHERE id='A';
            INSERT INTO applications.lots(candidate,cycle_id,mode) VALUES ('test','B','production');
            INSERT INTO applications.lot_dossiers
              SELECT l.id,d.id,1 FROM applications.lots l,applications.dossiers d WHERE l.cycle_id='B';
            INSERT INTO discovery.qualifications(id,version_id,cv_hash,prompt_hash,status,result)
              SELECT 'q'||n,n::text,sha256,'p',CASE WHEN n=25 THEN 'error' ELSE 'done' END,
                     CASE WHEN n=25 THEN NULL WHEN n=24 THEN '{"verdict":"écarter"}' ELSE '{"verdict":"retenir"}' END
              FROM generate_series(21,25) n,documents.cv_versions;
            INSERT INTO discovery.cycle_items SELECT 'A',version_id,id FROM discovery.qualifications WHERE id<>'q';
            INSERT INTO applications.dossiers(id,candidate,identity,mode,cycle_id,version_id,canonical_url,
                content,cv_sha256,uncertain)
                SELECT gen_random_uuid(),'test','cle-'||n,'production','A',n::text,
                'https://example.invalid','{}',sha256,false FROM generate_series(21,22) n,documents.cv_versions;
            INSERT INTO applications.submission_attempts(id,dossier_id,generation,version_id,cv_sha256,lease_until,status,outcome)
                SELECT gen_random_uuid(),id,1,version_id,cv_sha256,now(),
                   CASE version_id WHEN '21' THEN 'transmitting' ELSE 'no_submission' END,
                   CASE version_id WHEN '22' THEN '{"status":"blocked"}'::jsonb ELSE NULL END
                FROM applications.dossiers WHERE version_id IN ('21','22');
            UPDATE applications.submission_receipts SET observed_at='2026-11-03';
        """)
    os.environ["DASHBOARD_POSTGRES_DSN"] = "user=web_recette"
    with TestClient(app, base_url="http://localhost") as client:
        filters = {
            "cycle": "A",
            "du": "2026-10-01",
            "au": "2026-10-01",
            "lieu": "Rabat",
            "contrat": "CDI",
        }
        first = check_counts(client, filters, [31, 4, 1, 1, 4, 1, 25, 1, 1, 1, 1, 1, 2])
        assert "Semaine du 2026-11-02 · 1" in first
        check_counts(client, {"au": "2000-01-01"}, [0] * 13)
        check_counts(
            client, {"entreprise": "Alpha"}, [3, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0]
        )
        with psycopg.connect() as db:
            db.execute("""UPDATE applications.submission_attempts SET status='confirmed' WHERE version_id='21';
                INSERT INTO applications.submission_receipts(dossier_id,attempt_id,observed_at,evidence)
                SELECT dossier_id,id,'2026-11-18','{"url":"https://example.invalid/recu"}'
                FROM applications.submission_attempts WHERE version_id='21'""")
            # Rapprochement avec les tables sources de la recette.
            assert db.execute(
                "SELECT count(DISTINCT identity) FROM discovery.versions"
            ).fetchone() == (31,)
            assert db.execute(
                "SELECT count(*) FROM applications.submission_receipts"
            ).fetchone() == (2,)
            assert db.execute(
                "SELECT count(DISTINCT dossier_id),count(*) FROM applications.lot_dossiers"
            ).fetchone() == (1, 2)
        second = check_counts(
            client, filters, [31, 4, 2, 0, 4, 1, 25, 1, 2, 0, 1, 1, 2]
        )
        assert (
            "Semaine du 2026-11-09 · 0" in second
            and "Semaine du 2026-11-16 · 1" in second
        )
        mobile(client, work)
        assert client.get("/dashboard", params={"du": "invalid"}).status_code == 400
        assert (
            client.get(
                "/dashboard", headers={"Origin": "https://example.invalid"}
            ).status_code
            == 403
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
