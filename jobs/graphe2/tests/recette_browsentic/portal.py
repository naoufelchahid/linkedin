"""Portail isolé de recette. Servir uniquement sur loopback."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import token_hex

BASE = "http://127.0.0.1:18202"
PDF = Path(__file__).with_name("recette.pdf")


class Portal(BaseHTTPRequestHandler):
    def do_GET(self):
        headers = {}
        if self.path == "/start":
            headers["Set-Cookie"] = (
                f"recette={self.server.nonce}; Max-Age=3600; HttpOnly; SameSite=Lax; Path=/"
            )
            body = '<title>Recette</title><iframe id="cadre" src="/frame"></iframe>'
        elif self.path == "/frame":
            if "recette=" + self.server.nonce not in self.headers.get(
                "Cookie", ""
            ).split("; "):
                self.send_error(403, "Cookie de recette absent avant redemarrage")
                return
            body = "<p>Lecture du cadre " + self.server.nonce + "</p>"
        elif self.path == "/resume":
            cookie = "recette=" + self.server.nonce
            body = (
                "<p>"
                + (
                    "Session de recette retrouvee"
                    if cookie in self.headers.get("Cookie", "").split("; ")
                    else "Session absente"
                )
                + "</p>"
            )
        elif self.path == "/piece":
            body = """<title>Pièce de recette</title><input type=file id=piece accept="application/pdf">
                <output id=result></output><script>
                piece.onchange = async () => {
                  const digest = await crypto.subtle.digest("SHA-256", await piece.files[0].arrayBuffer());
                  result.textContent = Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, "0")).join("");
                };
                </script>"""
        elif self.path == "/recette.pdf":
            body = PDF.read_bytes()
            headers["Content-Disposition"] = 'attachment; filename="recette.pdf"'
        else:
            self.send_error(404)
            return
        mime = (
            "application/pdf" if isinstance(body, bytes) else "text/html; charset=utf-8"
        )
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(200)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def portal():
    server = ThreadingHTTPServer(("127.0.0.1", 18202), Portal)
    server.nonce = token_hex(12)
    return server
