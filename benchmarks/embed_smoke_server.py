"""Serve only a generated iframe fixture on loopback for browser verification."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/embed-smoke.html"):
            self.send_error(404)
            return
        body = Path(__file__).with_name("embed-smoke.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8519), Handler).serve_forever()
