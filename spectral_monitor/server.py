"""Loopback-only HTTP bridge for the external diagnostic collector."""
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
import stat
from .collector import ReportCollector, MAX_REPORT_BYTES


def load_token(token_file):
    path = os.path.abspath(token_file)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise PermissionError("Token file must be readable only by its owner (chmod 600)")
    with open(path, "r", encoding="utf-8") as handle:
        token = handle.read().strip()
    if len(token) < 32:
        raise ValueError("Bearer token must contain at least 32 characters")
    return token


def make_handler(collector, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.request.settimeout(5)

        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            body = json.dumps(collector.status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/v1/reports":
                self.send_error(404)
                return
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + token
            if not hmac.compare_digest(supplied, expected):
                self.send_error(401)
                return
            if self.headers.get("Transfer-Encoding") is not None:
                self.send_error(400, "Transfer-Encoding is not supported")
                return
            if self.headers.get_content_type() != "application/json":
                self.send_error(415)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > MAX_REPORT_BYTES:
                    raise ValueError("invalid report size")
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("truncated request body")
                result = collector.accept(raw.decode("utf-8"))
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, UnicodeError, json.JSONDecodeError):
                self.send_error(400)

        def log_message(self, *_args):
            return
    return Handler


def main():
    parser = ArgumentParser(description="Loopback-only Spectral Core diagnostic receiver")
    parser.add_argument("--token-file", required=True,
                        help="Path to a private file containing a 32+ character bearer token")
    parser.add_argument("--path", default="external-diagnostics.jsonl")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        token = load_token(args.token_file)
    except (OSError, ValueError, PermissionError) as error:
        parser.error(str(error))
    collector = ReportCollector(args.path)
    server = HTTPServer(("127.0.0.1", args.port), make_handler(collector, token))
    server.timeout = 1
    print(f"External monitor listening on 127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
