"""Servidor local do painel de flipping de RS3. Requer apenas Python."""

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from application import Application, RouteNotFound
from ledger import Ledger, integer
from market import Market

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/board.js": ("board.js", "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def deliver(self, status, media, payload, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def json(self, data, status=200):
        self.deliver(status, "application/json; charset=utf-8",
                     json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8"))

    def allowed(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        if host not in hosts or (origin and origin != f"http://{host}"):
            self.json({"error": "Abra o painel pelo endereço local informado."}, 403)
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        url = urlsplit(self.path)
        try:
            if url.path in ASSETS:
                name, media = ASSETS[url.path]
                self.deliver(200, media, (WEB / name).read_bytes())
            else:
                result = self.server.app.get(self.path)
                if url.path == "/api/exports/trades.csv":
                    self.deliver(200, "text/csv; charset=utf-8", result.encode("utf-8-sig"),
                                 {"Content-Disposition": 'attachment; filename="merch-rs3-historico.csv"'})
                else:
                    self.json(result)
        except RouteNotFound:
            self.json({"error": "Endereço inexistente."}, 404)
        except ValueError as error:
            self.json({"error": str(error)}, 400)

    def do_POST(self):
        if not self.allowed():
            return
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Envie os dados em JSON.")
            length = integer(self.headers.get("Content-Length"), "o tamanho do pedido", maximum=8192)
            data = json.loads(self.rfile.read(length))
            self.json(self.server.app.post(urlsplit(self.path).path, data))
        except RouteNotFound:
            self.json({"error": "Endereço inexistente."}, 404)
        except (ValueError, TypeError) as error:
            self.json({"error": str(error)}, 400)


class Server(ThreadingHTTPServer):
    def __init__(self, port, ledger):
        self.app = Application(ledger, Market(ledger))
        super().__init__(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Painel local de flipping para RuneScape 3.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=ROOT / ".merch" / "merch.sqlite3")
    args = parser.parse_args()
    args.data.parent.mkdir(parents=True, exist_ok=True)
    with Server(args.port, Ledger(args.data)) as server:
        print(f"Merch RS3: http://127.0.0.1:{server.server_port}/", flush=True)
        if os.environ.get("MERCH_OPEN_BROWSER") == "1":
            import webbrowser

            webbrowser.open(f"http://127.0.0.1:{server.server_port}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
