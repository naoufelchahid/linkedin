"""Recette sans identifiants : App Server, transport Unix et lettre synthétique."""

import asyncio
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from unittest.mock import patch


def inside():
    from linkedin_applications.browser import Browsentic
    from linkedin_applications.codex import Codex, Session
    from linkedin_applications.writer import Writer, schema

    class ThreadStarted(Exception):
        pass

    class Probe(Session):
        async def request(self, method, *args, **kwargs):
            if method == "turn/start":
                raise ThreadStarted
            return await super().request(method, *args, **kwargs)

    async def startup(root):
        # Le thread utilise la commande, la configuration et le sandbox normaux.
        # Le tour de modèle s’arrête avant tout appel au fournisseur.
        with patch("linkedin_applications.codex.Session", Probe):
            try:
                await Codex(root, writer=True, timeout=40).turn(
                    "fixture", schema(ok="boolean")
                )
            except ThreadStarted:
                pass
            else:
                raise AssertionError("thread/start attendu")
        command = ["socat", "STDIO", "UNIX-CONNECT:/mcp/fixture.sock"]
        async with Session(command, root) as rpc:
            await Browsentic(root, command, {}).connect(rpc)
            assert (await rpc.request("tools/list"))["tools"] == []

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        asyncio.run(startup(root))
        template = root / "modele.docx"
        with zipfile.ZipFile(template, "w") as doc:
            doc.writestr(
                "[Content_Types].xml",
                """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>""",
            )
            doc.writestr(
                "_rels/.rels",
                """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>""",
            )
            doc.writestr(
                "word/document.xml",
                """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Lettre synthetique de recette</w:t></w:r></w:p></w:body></w:document>""",
            )

        async def render(codex, *args):
            await asyncio.to_thread(
                subprocess.run,
                ["libreoffice", "--headless", "--convert-to", "pdf", "lettre.docx"],
                cwd=codex.cwd,
                capture_output=True,
                check=True,
                timeout=40,
            )
            await asyncio.to_thread(
                subprocess.run,
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-l",
                    "1",
                    "-scale-to",
                    "320",
                    "-png",
                    "lettre.pdf",
                    "page",
                ],
                cwd=codex.cwd,
                check=True,
                timeout=15,
            )
            assert (codex.cwd / "page-1.png").read_bytes().startswith(b"\x89PNG")
            return {"checked": True}

        with patch.object(Codex, "turn", render):
            pdf = Writer(root, template).letter({"dossier": "fixture", "offer": {}})
        content = subprocess.check_output(["pdftotext", pdf, "-"], timeout=15)
        assert b"Lettre synthetique de recette" in content
        assert os.stat(pdf).st_mode & 0o777 == 0o600
    print(
        "Thread App Server initialisé, MCP Unix consulté, lettre PDF rendue et contrôlée."
    )


class Fixture(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            req = json.loads(line)
            if "id" not in req:
                continue
            if req["method"] == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fixture", "version": "1"},
                }
            elif req["method"] == "tools/list":
                result = {"tools": []}
            else:
                raise ValueError("Méthode inattendue")
            self.wfile.write(
                (
                    json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result})
                    + "\n"
                ).encode()
            )


def run(image):
    with tempfile.TemporaryDirectory() as scratch:
        socket = Path(scratch) / "fixture.sock"
        with socketserver.UnixStreamServer(str(socket), Fixture) as server:
            os.chmod(socket, 0o600)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--network=none",
                        "--entrypoint",
                        "python",
                        "-v",
                        f"{Path(__file__).resolve()}:/check.py:ro",
                        "-v",
                        f"{scratch}:/mcp:ro",
                        image,
                        "/check.py",
                        "--inside",
                    ],
                    check=True,
                    timeout=120,
                )
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    if sys.argv[1] == "--inside":
        inside()
    else:
        run(sys.argv[1])
