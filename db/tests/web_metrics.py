"""Comparaison des agrégats SQL, des listes et de la fiche avec le même périmètre."""

import json
import os
import subprocess
import sys
import threading
import time
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

import psycopg
from linkedin_discovery.dashboard import app
from starlette.testclient import TestClient
from websockets.sync.client import connect


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


def keyboard_journey(socket):
    # CDP envoie les touches natives. Les expressions DOM ne font que lire la page
    # et le focus ; le navigateur gère les changements de focus et la navigation.
    sequence = 0

    def command(method, **params):
        nonlocal sequence
        sequence += 1
        socket.send(json.dumps({"id": sequence, "method": method, "params": params}))
        while True:
            response = json.loads(socket.recv(timeout=5))
            if response.get("id") == sequence:
                assert "error" not in response, response.get("error")
                return response["result"]

    def read(expression):
        return command("Runtime.evaluate", expression=expression, returnByValue=True)[
            "result"
        ].get("value")

    def key(name, code):
        for event in ("rawKeyDown", "keyUp"):
            command(
                "Input.dispatchKeyEvent",
                type=event,
                key=name,
                code=name,
                windowsVirtualKeyCode=code,
            )

    def wait_for(expression):
        deadline = time.monotonic() + 12
        while not read(expression):
            assert time.monotonic() < deadline, expression
            time.sleep(0.05)

    def follow(selector):
        wait_for(
            "document.readyState==='complete' && !!document.querySelector("
            + json.dumps(selector)
            + ")"
        )
        for _ in range(120):
            if read("document.activeElement.matches(" + json.dumps(selector) + ")"):
                break
            key("Tab", 9)
        else:
            raise AssertionError("Lien inaccessible au clavier : " + selector)
        previous = read("location.href")
        key("Enter", 13)
        wait_for(
            "location.href!=="
            + json.dumps(previous)
            + " && document.readyState==='complete'"
        )

    wait_for("document.readyState==='complete' && !!document.querySelector('.pie')")
    assert read("innerWidth<=500 && document.documentElement.scrollWidth<=innerWidth")
    follow(".pie svg a")
    listing = read("location.href")
    assert "cycle=A" in listing and "verdict=" in listing
    follow("#rows tbody a")
    follow("a.return")
    assert read("location.href") == listing


def mobile(client, work):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/dashboard"):
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
            base = f"http://127.0.0.1:{server.server_port}"
            profile = work / "metrics-profile"
            with subprocess.Popen(
                [
                    os.environ.get("CHROME", "google-chrome"),
                    "--headless",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-background-networking",
                    "--disable-dev-shm-usage",
                    "--remote-debugging-address=127.0.0.1",
                    "--remote-debugging-port=0",
                    f"--user-data-dir={profile}",
                    "--window-size=390,844",
                    base + "/dashboard?cycle=A",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ) as browser:
                try:
                    deadline = time.monotonic() + 30
                    port_file = profile / "DevToolsActivePort"
                    while not port_file.exists():
                        assert browser.poll() is None and time.monotonic() < deadline
                        time.sleep(0.05)
                    port = int(port_file.read_text().splitlines()[0])
                    with urlopen(
                        f"http://127.0.0.1:{port}/json/list", timeout=5
                    ) as events:
                        tab = next(
                            t
                            for t in json.load(events)
                            if t["type"] == "page" and t["url"].startswith(base)
                        )
                    with connect(
                        tab["webSocketDebuggerUrl"], open_timeout=5, close_timeout=2
                    ) as socket:
                        keyboard_journey(socket)
                finally:
                    browser.terminate()
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
