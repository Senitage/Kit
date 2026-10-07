"""Chrome's tabs, from Kit's browser extension.

The extension (``browser_extension/``, loaded into Chrome or Edge) posts every
open tab and the one Dan is looking at to ``http://127.0.0.1:8765/tabs``
whenever tabs change, and every 30 seconds. ``BrowserListener`` takes those
posts. It listens on 127.0.0.1 only, so nothing off this PC can reach it and
Windows doesn't ask about the firewall, and it only accepts requests from Kit's
own extension, so a web page can't feed it fake tabs.

``clean_url`` drops query strings and #fragments (they often carry search
terms, session ids or tokens) before anything leaves the PC. The privacy
filter in ``kit.desk.watch`` then blanks hidden sites.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765
# The extension's ID is fixed by the public key in its manifest.json, so it's the
# same in Chrome and Edge and on every PC.
EXTENSION_ID = "dhjlcedoafkkbbdapnnffdahoilemnmf"
FRESH_FOR_S = 90.0  # the extension reports at least every 30 seconds
MAX_BODY = 512 * 1024
BROWSER_APPS = {"Chrome", "Edge", "Brave"}


def clean_url(url: str) -> tuple[str, str]:
    """(the address without its query or fragment, the site) for one tab."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "", ""
    if parts.scheme in ("http", "https"):
        site = (parts.hostname or "").removeprefix("www.")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), site
    if parts.scheme == "file":
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), "local file"
    if parts.scheme in ("chrome", "edge"):
        return f"{parts.scheme}://{parts.netloc}", "browser page"
    if parts.scheme == "about":
        return "", "browser page"
    return "", ""  # extension pages, data: and blob: addresses say nothing useful


class BrowserFeed:
    """The latest tabs from the extension, kept while they're fresh."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._latest: dict | None = None
        self._at = float("-inf")

    def update(self, payload: dict) -> None:
        tabs = [t for t in payload.get("tabs", []) if isinstance(t, dict)][:300]
        focused = payload.get("focused")
        latest = {
            "name": str(payload.get("browser") or "Chrome")[:50],
            "tabs": tabs,
            "focused": focused if isinstance(focused, dict) else None,
        }
        with self._lock:
            self._latest, self._at = latest, self.clock()

    def current(self) -> dict | None:
        with self._lock:
            if self._latest is None or self.clock() - self._at > FRESH_FOR_S:
                return None
            return self._latest

    @property
    def connected(self) -> bool:
        return self.current() is not None


class BrowserListener:
    """A tiny HTTP server on 127.0.0.1 for the extension. Runs on its own thread."""

    def __init__(
        self,
        feed: BrowserFeed,
        watching: Callable[[], bool],
        port: int = DEFAULT_PORT,
        extension_ids: tuple[str, ...] = (EXTENSION_ID,),
    ) -> None:
        allowed = {f"chrome-extension://{i}" for i in extension_ids}

        class Handler(BaseHTTPRequestHandler):
            def _allowed(self) -> bool:
                return self.headers.get("Origin", "") in allowed

            def _send(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                origin = self.headers.get("Origin", "")
                if origin in allowed:
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self) -> None:  # noqa: N802 (http.server's name)
                if not self._allowed():
                    self._send(403, {"error": "not Kit's extension"})
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                self.send_header("Access-Control-Allow-Methods", "GET, POST")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                # Read the body before any answer, even a refusal: closing a socket with
                # unread data makes Windows reset the connection under the reply.
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self.close_connection = True
                    self._send(413, {"error": "too big"})
                    return
                body = self.rfile.read(length) if length > 0 else b""
                if not self._allowed():
                    self._send(403, {"error": "not Kit's extension"})
                    return
                if self.path == "/ping":  # the extension's popup asking if Kit is there
                    self._send(200, {"ok": True, "watching": watching()})
                    return
                if self.path != "/tabs":
                    self._send(404, {"error": "no such page"})
                    return
                if not body:
                    self._send(400, {"error": "not JSON"})
                    return
                try:
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise ValueError("not an object")
                except ValueError:
                    self._send(400, {"error": "not JSON"})
                    return
                feed.update(payload)
                self._send(200, {"ok": True, "watching": watching()})

            def log_message(self, fmt, *args) -> None:
                log.debug("extension: " + fmt, *args)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]

    def start(self) -> None:
        threading.Thread(target=self.server.serve_forever, name="kit-browser", daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
