"""Optional loopback-only HTTP bridge for the standalone diagnostic collector."""
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
from .collector import ReportCollector


def make_handler(collector, token):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            body = json.dumps(collector.status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
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
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 16384:
                    raise ValueError("invalid report size")
                result = collector.accept(self.rfile.read(size).decode("utf-8"))
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, UnicodeError, json.JSONDecodeError):
                self.send_error(400)

        def log_message(self, *_args):
            return
    return Handler


def main():
    parser = ArgumentParser(description="Spectral Core external diagnostic receiver")
    parser.add_argument("--token", required=True, help="Bearer token; keep it out of source control")
    parser.add_argument("--path", default="external-diagnostics.jsonl")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Loopback only by default; change only behind a secured network")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    collector = ReportCollector(args.path)
    server = HTTPServer((args.host, args.port), make_handler(collector, args.token))
    print(f"External monitor listening on {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
