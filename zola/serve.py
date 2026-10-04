#!/usr/bin/env python3
"""Static server for the Zola preview, behaving like GitHub Pages where it
matters: /x 301s to /x/ (http.server does this already), and a miss serves
/404.html with status 404.

usage: serve.py <dir> <port> [--jekyll]   (binds 127.0.0.1; tailscale serve fronts it)

--jekyll serves a Jekyll _site the way Pages does (/x -> x.html), for
side-by-side screenshots.
"""

import functools
import http.server
import sys
from pathlib import Path

root, port = Path(sys.argv[1]).resolve(), int(sys.argv[2])
jekyll = "--jekyll" in sys.argv


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = super().translate_path(path)
        if jekyll and not Path(p).exists() and Path(p + ".html").exists():
            return p + ".html"
        return p

    def send_error(self, code, message=None, explain=None):
        page = root / "404.html"
        if code == 404 and page.exists():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        super().send_error(code, message, explain)

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(
    ("127.0.0.1", port), functools.partial(Handler, directory=str(root))
).serve_forever()
