"""Rejouer un lot fictif dans Chrome habituel, avec PostgreSQL et Docker jetables."""

import argparse
import json
import os
import re
import secrets
import select
import shlex
import shutil
import socketserver
import subprocess
import tempfile
import threading
from contextlib import ExitStack
from email import policy
from email.parser import BytesParser
from hashlib import sha256
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import sleep
from urllib.parse import urlsplit
from zipfile import ZipFile

from linkedin_discovery.dashboard import app
from starlette.testclient import TestClient

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CYCLE = "a" * 32
TITLE = "Analyste de données"
COMPANY = "Atelier Atlas"
RECIPIENT = "recrutement@example.invalid"
FIXTURE = HERE.parent / "recette_browsentic/recette.pdf"
FORM = """<!doctype html><html lang="fr"><meta charset="utf-8">
<title>Offre de recette</title><h1>Analyste de données — Atelier Atlas</h1>
<p>Lettre obligatoire</p>
<form method="post" action="/recu" enctype="multipart/form-data">
<label>CV de recette <input type="file" id="cv" name="cv" required></label>
<output id="cv_hash">cv: vide</output>
<label>Lettre de recette <input type="file" id="letter" name="letter" required></label>
<output id="letter_hash">letter: vide</output>
<button id="deposer">Déposer sur le portail de recette</button></form>
<script>
for (const id of ['cv', 'letter']) {
  const field = document.getElementById(id);
  field.onchange = async () => {
    const bytes = await field.files[0].arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const hex = Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, '0')).join('');
    document.getElementById(id + '_hash').textContent = id + ': ' + hex;
  };
}
</script>"""


class Portal(BaseHTTPRequestHandler):
    def send(self, status, body, mime="text/html; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        request = urlsplit(self.path)
        path = request.path
        if path == "/offre":
            self.send(200, FORM.encode())
        elif path == "/recu" and self.server.uploads:
            self.send(
                200,
                (
                    '<!doctype html><meta charset="utf-8"><h1>RECETTE-ATLAS — '
                    + escape(TITLE)
                    + "</h1>"
                ).encode(),
            )
        elif (
            path in ("/piece/cv.pdf", "/piece/letter.pdf", "/piece/autre.pdf")
            and request.query == "recette=" + self.server.token
        ):
            doc = self.server.work / Path(path).name
            if not doc.is_file():
                self.send_error(404)
                return
            self.send(
                200,
                doc.read_bytes(),
                "application/pdf",
                {
                    "Content-Disposition": (
                        f'attachment; filename="recette-{self.server.token}-{doc.name}"'
                    )
                },
            )
        elif path.startswith("/dashboard/"):
            response = self.server.dashboard.get(self.path)
            self.send(
                response.status_code, response.content, response.headers["content-type"]
            )
        else:
            self.send_error(404)

    def do_POST(self):
        size = int(self.headers["Content-Length"])
        paths = {kind: self.server.work / (kind + ".pdf") for kind in ("cv", "letter")}
        if (
            self.path != "/recu"
            or self.server.uploads
            or not all(path.is_file() for path in paths.values())
            or not 0
            < size
            <= sum(path.stat().st_size for path in paths.values()) + 65536
        ):
            self.send_error(400)
            return
        message = BytesParser(policy=policy.default).parsebytes(
            ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode()
            + self.rfile.read(size)
        )
        pieces = {
            part.get_param("name", header="content-disposition"): part.get_payload(
                decode=True
            )
            for part in message.iter_parts()
        }
        expected = {kind: path.read_bytes() for kind, path in paths.items()}
        if pieces != expected:
            self.send_error(422)
            return
        self.server.uploads.append(
            [sha256(pieces[k]).hexdigest() for k in ("cv", "letter")]
        )
        self.send(303, b"", headers={"Location": "/recu"})

    def log_message(self, *_):
        pass


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        with subprocess.Popen(
            ["browsentic", "mcp"],
            stdin=self.request,
            stdout=self.request,
            stderr=subprocess.DEVNULL,
        ) as bridge:
            bridge.wait(timeout=240)


def rendered_receipt(url, digest, portal_url):
    with subprocess.Popen(
        ["browsentic", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    ) as bridge:
        serial = 0

        def rpc(method, params=None):
            nonlocal serial
            serial += 1
            request = {"jsonrpc": "2.0", "method": method, "params": params or {}}
            if method != "notifications/initialized":
                request["id"] = serial
            bridge.stdin.write(json.dumps(request).encode() + b"\n")
            bridge.stdin.flush()
            if "id" not in request:
                return None
            while select.select([bridge.stdout], [], [], 7)[0]:
                line = bridge.stdout.readline()
                assert line, "Relais MCP fermé"
                response = json.loads(line)
                if response.get("id") == serial:
                    result = response["result"]
                    assert not result.get("isError"), method
                    return result
            raise TimeoutError(method)

        def page(name, **arguments):
            result = rpc("tools/call", {"name": name, "arguments": arguments})
            if result.get("structuredContent"):
                return result["structuredContent"]
            text = result["content"][0]["text"]
            return json.loads(text[text.index("{") : text.rindex("}") + 1])

        try:
            rpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "recette-dashboard", "version": "1"},
                },
            )
            rpc("notifications/initialized")
            tab = page("page_openTab", url=url, active=True)["tabId"]
            for _ in range(20):
                current = page("page_switchTab")
                active = next(
                    (entry for entry in current["tabs"] if entry["tabId"] == tab), {}
                )
                if (
                    current["activeTabId"] == tab
                    and (current.get("url") or active.get("url")) == url
                ):
                    text = page("page_extractText")
                    if digest in (text.get("text") or text.get("content", "")):
                        for entry in current["tabs"]:
                            if entry.get("url") == portal_url:
                                page("page_closeTab", tabId=entry["tabId"])
                        return
                sleep(0.2)
            raise AssertionError("Empreinte du reçu absente de la fiche dans Chrome")
        finally:
            bridge.terminate()


def serve(cleanup, server):
    cleanup.enter_context(server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cleanup.callback(thread.join)
    cleanup.callback(server.shutdown)
    return server


def clean_captures(token):
    store = json.loads(subprocess.check_output(["browsentic", "downloads", "--json"]))
    folder = Path(store["dir"]).resolve()
    for capture in store["downloads"]:
        name = capture["name"]
        if capture["host"] == "127.0.0.1" and name in {
            f"recette-{token}-{piece}.pdf" for piece in ("cv", "letter", "autre")
        }:
            path = Path(capture["savedTo"])
            assert path.parent.resolve() == folder and path.name.endswith("-" + name)
            path.unlink(missing_ok=True)


def run(args, work):
    source_pdf = args.cv.read_bytes()
    assert source_pdf.startswith(b"%PDF-"), "Le fichier source doit être un PDF"
    source_hash = sha256(source_pdf).hexdigest()
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    password = secrets.token_hex(24)
    env.update(
        POSTGRES_PASSWORD=password,
        PGPASSWORD=password,
        PGUSER="postgres",
        PGHOST="127.0.0.1",
        PGDATABASE="postgres",
    )
    with ExitStack() as cleanup:
        pg = subprocess.check_output(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "-e",
                "POSTGRES_PASSWORD",
                "-p",
                "127.0.0.1::5432",
                "postgres:17",
            ],
            env=env,
            text=True,
        ).strip()
        cleanup.callback(
            subprocess.run,
            ["docker", "rm", "-f", "-v", pg],
            stdout=subprocess.DEVNULL,
            check=False,
        )
        address = subprocess.check_output(["docker", "port", pg, "5432/tcp"], text=True)
        env["PGPORT"] = address.strip().rsplit(":", 1)[1]
        psql = ["psql", "-XqAt", "-v", "ON_ERROR_STOP=1"]
        for _ in range(60):
            if (
                subprocess.run(
                    ["docker", "exec", pg, "pg_isready", "-q", "-h", "127.0.0.1"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                == 0
            ):
                break
            sleep(1)
        for name in ("bootstrap.sql", "migrate.sql"):
            subprocess.check_call(
                psql + ["-f", str(ROOT / "db" / name)],
                env=env,
                stdout=subprocess.DEVNULL,
            )

        def sql(query, *variables):
            return subprocess.check_output(
                psql + list(variables), input=query, env=env, text=True
            ).strip()

        dashboard = cleanup.enter_context(TestClient(app, base_url="http://127.0.0.1"))
        portal = ThreadingHTTPServer(("127.0.0.1", 0), Portal)
        portal.work, portal.dashboard, portal.uploads = work, dashboard, []
        portal.token = secrets.token_hex(12)
        cleanup.callback(clean_captures, portal.token)
        serve(cleanup, portal)
        base = f"http://127.0.0.1:{portal.server_port}"
        bridge = serve(
            cleanup,
            socketserver.ThreadingUnixStreamServer(str(work / "chrome.sock"), Relay),
        )
        bridge.daemon_threads = True

        source_hex = source_pdf.hex()
        seed_cv = "CREATE TEMP TABLE cv_input (hex text);\nCOPY cv_input FROM STDIN;\n"
        sql(
            seed_cv
            + source_hex
            + "\n\\.\n"
            + r"""
        \getenv password PGPASSWORD
        CREATE ROLE recette LOGIN PASSWORD :'password' IN ROLE linkedin_applications;
        CREATE ROLE recette_web LOGIN PASSWORD :'password' IN ROLE linkedin_web;
        INSERT INTO documents.cv_versions(sha256,pdf,markdown,provenance)
        SELECT encode(sha256(pdf),'hex'),pdf,
            'Camille Martin. Expérience fictive : synthèse de relevés et analyses SQL.', 'recette'
        FROM (SELECT decode(hex, 'hex') AS pdf FROM cv_input) doc;
        INSERT INTO discovery.cycles
        SELECT :'cycle', now(), sha256, markdown, 'p', 'p', '{}', 'done' FROM documents.cv_versions;
        INSERT INTO discovery.versions(id,offer_key,content,canonical_url)
        VALUES ('v-recette',repeat('b',64),jsonb_build_object(
          'key',repeat('b',64),'title',:'title','company',:'company','url',:'url',
          'description', :'description'),:'url');
        INSERT INTO discovery.occurrences(cycle_id, profile, raw_hash, raw, version_id, observed_at)
        VALUES (:'cycle','recette','fixture','{}','v-recette',now());
        INSERT INTO discovery.qualifications(id,version_id,cv_hash,prompt_hash,status,result)
        SELECT 'q-recette','v-recette',sha256,'p','done',
            '{"verdict":"retenir","incertitude":false}' FROM documents.cv_versions;
        INSERT INTO discovery.cycle_items VALUES (:'cycle','v-recette','q-recette');
        """,
            "-v",
            f"cycle={CYCLE}",
            "-v",
            f"title={TITLE}",
            "-v",
            f"company={COMPANY}",
            "-v",
            f"url={base}/offre",
            "-v",
            f"description=Analyser des relevés. Recrutement : {RECIPIENT}",
        )

        def dsn(user):
            return f"host=127.0.0.1 hostaddr=127.0.0.1 port={env['PGPORT']} dbname=postgres user={user} password={password}"

        os.environ.update(
            DASHBOARD_POSTGRES_DSN=dsn("recette_web"),
            APPLICATIONS_STATE="/recette/etat",
            DISCOVERY_HOME=str(work),
            APPLICATIONS_CANDIDATE="recette",
            APPLICATIONS_POSTGRES_DSN=dsn("recette"),
        )
        assert (
            sql("""
          SELECT (SELECT count(*) FROM applications.lots),
                 (SELECT count(*) FROM applications.dossiers),
                 (SELECT count(*) FROM runtime_g2.checkpoints)
        """)
            == "0|0|0"
        )
        print("File neuve : zéro lot, dossier et checkpoint.", flush=True)

        with ZipFile(work / "modele.docx", "w") as model:
            model.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>",
            )
            model.writestr(
                "_rels/.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                "</Relationships>",
            )
            model.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>Canevas de recette</w:t></w:r></w:p></w:body></w:document>",
            )
        (work / "humanizer.txt").write_text(
            "Préfère un français simple, précis et naturel."
        )
        (work / "policy.json").write_text("{}")
        auth = work / "auth"
        auth.mkdir(mode=0o700)
        if not args.local_writing:
            shutil.copyfile(args.auth, auth / "auth.json")
            (auth / "auth.json").chmod(0o600)
        docker = [
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            "--log-driver",
            "none",
            "-e",
            "APPLICATIONS_POSTGRES_DSN",
            "-e",
            "APPLICATIONS_CANDIDATE",
            "-v",
            f"{work}:/recette",
            "-v",
            f"{HERE / 'worker.py'}:/worker-recette.py:ro",
        ]
        launcher = work / "launch"
        launcher.write_text(
            "#!/bin/sh\nexec "
            + shlex.join(docker + [args.image])
            + ' "$@" --queue-only\n'
        )
        launcher.chmod(0o700)
        os.environ["APPLICATIONS_CLI"] = str(launcher)
        launched = dashboard.post(
            "/dashboard/actions/applications",
            json={"cycle": CYCLE, "mode": "production"},
        )
        assert launched.status_code == 200, launched.text
        lot = launched.json()["lot"]
        print(
            "Lot ouvert depuis le tableau de bord dans PostgreSQL jetable.", flush=True
        )
        try:
            subprocess.run(
                docker
                + [
                    "-e",
                    "CODEX_HOME=/recette/auth",
                    "-e",
                    f"RECETTE_REDACTION_LOCALE={int(args.local_writing)}",
                    "-e",
                    "APPLICATIONS_TELEGRAM_TOKEN=fixture",
                    "-e",
                    "APPLICATIONS_TELEGRAM_CHAT=1",
                    "-e",
                    "APPLICATIONS_LETTER_TEMPLATE=/recette/modele.docx",
                    "-e",
                    "APPLICATIONS_HUMANIZER=/recette/humanizer.txt",
                    "-e",
                    "APPLICATIONS_BROWSER_POLICY=/recette/policy.json",
                    "-e",
                    'APPLICATIONS_BROWSER_COMMAND=["socat","STDIO","UNIX-CONNECT:/recette/chrome.sock"]',
                    "--entrypoint",
                    "python",
                    args.image,
                    "/worker-recette.py",
                    base,
                    portal.token,
                ],
                check=True,
                timeout=430,
            )
        finally:
            shutil.rmtree(auth)
        proof = json.loads((work / "preuve.json").read_text())
        assert portal.uploads == [proof["pieces"]]
        assert proof["pieces"][0] == source_hash
        print(
            "SHA-256 du fichier source égal à celui du CV reçu sur le portail.",
            flush=True,
        )
        assert (
            sql("""
           SELECT (SELECT count(*) FROM applications.lots),
                  (SELECT count(*) FROM applications.dossiers),
                  (SELECT count(*) FROM applications.submission_receipts),
                  (SELECT count(*) FROM applications.followup_reviews WHERE approved_at IS NULL),
                  (SELECT count(*) FROM applications.followup_sends)
        """)
            == "1|1|1|1|0"
        )
        listing = dashboard.get("/dashboard/offres?q=Atelier")
        match = re.search(
            r'href="(/dashboard/offres/[a-f0-9]+)(?:[?"]|$)', listing.text
        )
        assert match, listing.status_code
        detail = dashboard.get(match[1])
        assert detail.status_code == 200
        for text in (
            TITLE,
            COMPANY,
            "Suivi à approuver",
            "Reçu de dépôt",
            "Empreinte SHA-256",
        ):
            assert text in detail.text, text
        assert (
            sql("SELECT state,deposit FROM api.suivi_candidatures_v1;")
            == "suivi à approuver|confirmé"
        )
        receipt_hash = sql(
            "SELECT encode(sha256(convert_to(evidence::text,'UTF8')),'hex') "
            "FROM applications.submission_receipts;"
        )
        assert receipt_hash in detail.text
        rendered_receipt(base + match[1], receipt_hash, base + "/recu")
        proof.update(
            lot=lot,
            dashboard=match[1],
            portal_post_count=1,
            receipt_sha256=receipt_hash,
        )
        args.proof.mkdir(mode=0o700, parents=True, exist_ok=True)
        (args.proof / "preuve.json").write_text(
            json.dumps(proof, indent=2, ensure_ascii=False)
        )
        css = dashboard.get("/dashboard/assets/css")
        assert css.status_code == 200
        html = detail.text.replace(
            '<link rel="stylesheet" href="/dashboard/assets/css">',
            "<style>" + css.text + "</style>",
        )
        (args.proof / "fiche.html").write_text(html)
        print(
            "Reçu confirmé sur la fiche du tableau de bord. Un dépôt local, zéro tentative de courriel.",
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--auth",
        type=Path,
        help="Copie de travail de l’authentification Codex",
    )
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument(
        "--cv", type=Path, default=FIXTURE, help="PDF utilisé dans la recette locale"
    )
    parser.add_argument(
        "--local-writing",
        action="store_true",
        help="Texte de lettre et brouillon déterministes, sans appel au modèle",
    )
    args = parser.parse_args()
    if not args.local_writing and args.auth is None:
        parser.error("--auth est requis pour une rédaction authentifiée")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="recette-linkedin-") as scratch:
        run(args, Path(scratch))
