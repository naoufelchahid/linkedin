"""Transport Browsentic simulé ; le portail HTTP reçoit les octets via le loopback."""

import asyncio
import json
import os
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import Request, urlopen

from linkedin_applications.browser import Browsentic
from linkedin_applications.codex import ConnectorError
from linkedin_applications.postgres_queue import PostgresQueue


def check(root, base, received):
    queue = PostgresQueue(root, os.environ["APPLICATIONS_POSTGRES_DSN"], "test")
    item = next(i for i in queue.items() if i["mode"] == "recipe")
    assert Path(item["cv"]).read_bytes() == b"%PDF A"
    source = root / "lettre.pdf"
    source.write_bytes(b"%PDF lettre")
    assert queue.dossier_document(item["dossier"], "letter") is None
    letter = Path(queue.dossier_letter(item["dossier"], source))
    source.write_bytes(b"%PDF autre")
    assert Path(queue.dossier_letter(item["dossier"], source)) == letter
    letter.unlink()
    letter = Path(queue.dossier_letter(item["dossier"]))
    item.update(letter=str(letter), letter_hash=sha256(b"%PDF lettre").hexdigest())
    registry = root / "policy.json"

    def publish(cv_id):
        registry.write_text(
            json.dumps(
                {
                    "files": {
                        item["cv_hash"]: cv_id,
                        item["letter_hash"]: {"downloadId": "letter-session-2"},
                    }
                }
            )
        )

    def post(field, data):
        with urlopen(Request(base + "/" + field, data=data), timeout=3) as response:
            assert response.status == 204

    class Session:
        def __init__(self, files):
            self.files = files

        async def request(self, method, params=None):
            if method == "tools/list":
                return {"tools": []}
            name = params["name"]
            if name == "page_switchTab":
                result = {"activeTabId": 1, "url": base}
            elif name in {"page_listFiles", "page_listDownloads"}:
                group = "files" if name == "page_listFiles" else "downloads"
                result = {
                    group: [
                        {"id": key, "size": len(data)}
                        for key, data in self.files.items()
                    ]
                }
            else:
                raise AssertionError(f"Appel non vérifié : {name}")
            return {"structuredContent": result}

    class ByteSession(Session):
        async def pin_attachment(self, reference):
            key = next(iter(reference.values()))
            data = self.files[key]

            async def send(target, verified_bytes):
                field = target["selector"].removeprefix("#")
                await asyncio.to_thread(post, field, verified_bytes)
                return {"content": [{"type": "text", "text": "ok"}]}

            return data, send

    def attach(browser, session, role, state=item):
        asyncio.run(
            browser.attach_document(
                session, 1, base, state, role, {"selector": "#" + role}
            )
        )

    def blocked(call, expected):
        try:
            call()
        except ConnectorError as exc:
            assert str(exc) == expected
        else:
            raise AssertionError("Blocage attendu")

    publish("cv-session-1")
    browser = Browsentic(root, [], {}, policy_path=registry)
    blocked(
        lambda: attach(browser, Session({"cv-session-1": b"%PDF A"}), "cv"),
        "browsentic_cv_session_bytes_unverified",
    )
    blocked(
        lambda: attach(browser, ByteSession({"cv-session-1": b"%PDF B"}), "cv"),
        "browsentic_cv_session_bytes_mismatch",
    )
    assert not received
    attach(browser, ByteSession({"cv-session-1": b"%PDF A"}), "cv")
    browser = Browsentic(root, [], {}, policy_path=registry)
    session = ByteSession(
        {
            "cv-session-2": b"%PDF A",
            "wrong-cv": b"%PDF B",
            "letter-session-2": b"%PDF lettre",
        }
    )
    blocked(lambda: attach(browser, session, "cv"), "browsentic_cv_reference_expired")
    blocked(
        lambda: attach(browser, session, "letter", {**item, "letter": ""}),
        "browsentic_letter_missing",
    )
    blocked(
        lambda: attach(browser, session, "cv", {**item, "cv": str(letter)}),
        "browsentic_cv_integrity",
    )
    assert len(received) == 1
    browser = Browsentic(root, [], {}, policy_path=registry, documents=queue)
    publish("cv-session-2")
    attach(browser, session, "cv")
    attach(browser, session, "letter")
    assert received == [
        ("/cv", item["cv_hash"]),
        ("/cv", item["cv_hash"]),
        ("/letter", item["letter_hash"]),
    ]


def main():
    received = []

    class Portal(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path in {"/cv", "/letter"}
            received.append(
                (
                    self.path,
                    sha256(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    ).hexdigest(),
                )
            )
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    with TemporaryDirectory() as root, HTTPServer(("127.0.0.1", 0), Portal) as server:
        serving = Thread(target=server.serve_forever)
        serving.start()
        try:
            check(Path(root), f"http://127.0.0.1:{server.server_port}", received)
        finally:
            server.shutdown()
            serving.join()
    print(
        "Portail HTTP local : empreintes du CV A et de la lettre confirmées après renouvellement."
    )


if __name__ == "__main__":
    main()
