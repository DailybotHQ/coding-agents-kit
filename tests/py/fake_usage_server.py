"""A loopback HTTP server that plays a vendor's usage endpoint in tests.

Importable (`FakeUsageServer`) and runnable:

    python3 fake_usage_server.py --routes ROUTES.json --port-file PORT --log LOG

Routes map a path to {"status": 200, "json": {...}} or {"body": "text"}, with
optional "delay" (seconds), "headers", "redirect" (a Location) and
"by_bearer" ({token: route keys to override for that credential}). The routes
file is re-read on every request, so a test can change the mode while the
server runs. The request log keeps the path, the method and a short sha256 of
the Authorization header (never the header itself), so a test can assert
which credential reached which path without a secret entering a log.
Standard library only; works the same on Windows, macOS and Linux.
"""

import argparse
import hashlib
import http.server
import json
import threading
import time


def digest(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:12]


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _routes(self):
        server = self.server
        if server.routes_file:
            with open(server.routes_file, "r", encoding="utf-8") as handle:
                return json.load(handle)
        return server.routes

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        entry = {"path": self.path, "method": "GET", "auth": digest(auth) if auth else "",
                 "headers": sorted(k.lower() for k in self.headers.keys())}
        self.server.requests.append(entry)
        if self.server.log_file:
            with open(self.server.log_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        route = self._routes().get(self.path.split("?")[0])
        if route is not None and "by_bearer" in route:
            # per-credential answers: {"by_bearer": {"<token>": {route}}, ...default route keys...}
            token = auth[7:] if auth.startswith("Bearer ") else auth
            override = route["by_bearer"].get(token)
            route = dict(route, **override) if override is not None else route
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        if route.get("delay"):
            time.sleep(route["delay"])
        if route.get("redirect"):
            self.send_response(302)
            self.send_header("Location", route["redirect"])
            self.end_headers()
            return
        if "json" in route:
            body = json.dumps(route["json"]).encode("utf-8")
        elif "size" in route:
            body = b"x" * int(route["size"])
        else:
            body = route.get("body", "").encode("utf-8")
        self.send_response(route.get("status", 200))
        self.send_header("Content-Type", route.get("content_type", "application/json"))
        for name, value in route.get("headers", {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class FakeUsageServer(object):
    def __init__(self, routes=None, routes_file=None, log_file=None):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.routes = routes or {}
        self.httpd.routes_file = routes_file
        self.httpd.log_file = log_file
        self.httpd.requests = []
        self.thread = None

    @property
    def port(self):
        return self.httpd.server_address[1]

    @property
    def base(self):
        return "http://127.0.0.1:%d" % self.port

    @property
    def requests(self):
        return self.httpd.requests

    def set_routes(self, routes):
        self.httpd.routes = routes

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", required=True)
    ap.add_argument("--port-file", required=True)
    ap.add_argument("--log", default=None)
    args = ap.parse_args()
    server = FakeUsageServer(routes_file=args.routes, log_file=args.log)
    with open(args.port_file, "w") as handle:
        handle.write(str(server.port))
    try:
        server.httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
