"""Source locale éphémère du seul CV autorisé, pour l'API buffer de Playwright."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import hashlib
import secrets
import threading


@contextmanager
def cv_buffer_source(path, expected_hash):
    content = Path(path).read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError('cv_changed_before_upload')
    route = '/' + secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not secrets.compare_digest(self.path, route):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}{route}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
