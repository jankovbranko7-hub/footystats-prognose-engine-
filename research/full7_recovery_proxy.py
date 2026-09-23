#!/usr/bin/env python3
from __future__ import annotations
import http.server
import os
import urllib.request
from urllib.error import HTTPError, URLError

PORT = int(os.environ.get("PORT", "10000"))
UPSTREAM_BASE = os.environ["FULL7_RECOVERY_UPSTREAM_BASE"].rstrip("/") + "/"
PROXY_TOKEN = os.environ["FULL7_RECOVERY_PROXY_TOKEN"]

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        prefix = f"/{PROXY_TOKEN}/"
        if not self.path.startswith(prefix):
            self.send_error(404)
            return
        leaf = self.path[len(prefix):].split("?", 1)[0]
        if not (
            leaf in {"index.json", "recovery.key"}
            or (leaf.startswith("part-") and leaf.endswith(".tar.enc"))
        ):
            self.send_error(404)
            return
        url = UPSTREAM_BASE + leaf
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "full7-recovery-proxy/1.0"})
            with urllib.request.urlopen(req, timeout=120) as upstream:
                self.send_response(200)
                ctype = upstream.headers.get("Content-Type", "application/octet-stream")
                self.send_header("Content-Type", ctype)
                clen = upstream.headers.get("Content-Length")
                if clen:
                    self.send_header("Content-Length", clen)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    block = upstream.read(1024 * 1024)
                    if not block:
                        break
                    self.wfile.write(block)
        except (BrokenPipeError, ConnectionResetError):
            return
        except (HTTPError, URLError, TimeoutError) as exc:
            try:
                self.send_error(502, explain=type(exc).__name__)
            except Exception:
                pass

if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
