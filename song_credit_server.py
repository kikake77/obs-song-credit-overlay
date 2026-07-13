import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import song_credit_core as core


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17321


def resource_path(relative_path):
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, relative_path)


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _handler_class(state_store, overlay_path):
    class OverlayRequestHandler(BaseHTTPRequestHandler):
        server_version = "SongCreditManagerForOBS/{}".format(core.APP_VERSION)

        def _send_bytes(self, status, content_type, data):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, "application/json; charset=utf-8", data)

        def do_GET(self):
            path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
            if path in ("/", "/overlay"):
                try:
                    with open(overlay_path, "rb") as handle:
                        data = handle.read()
                except OSError as exc:
                    self._send_json(500, {"error": "オーバーレイを読み込めません", "detail": str(exc)})
                    return
                self._send_bytes(200, "text/html; charset=utf-8", data)
                return
            if path == "/api/state":
                self._send_json(200, state_store.snapshot())
                return
            if path == "/health":
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "app": core.APP_NAME,
                        "version": core.APP_VERSION,
                    },
                )
                return
            if path == "/favicon.ico":
                self._send_bytes(204, "image/x-icon", b"")
                return
            self._send_json(404, {"error": "not found"})

        def log_message(self, format_text, *args):
            return

    return OverlayRequestHandler


class OverlayServer(object):
    def __init__(self, state_store, host=DEFAULT_HOST, port=DEFAULT_PORT, overlay_path=None):
        self.state_store = state_store
        self.host = host
        self.port = int(port)
        self.overlay_path = overlay_path or resource_path(os.path.join("web", "overlay.html"))
        self._server = None
        self._thread = None

    @property
    def running(self):
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def overlay_url(self):
        return "http://{}:{}/overlay".format(self.host, self.port)

    @property
    def health_url(self):
        return "http://{}:{}/health".format(self.host, self.port)

    def start(self):
        if self.running:
            return self.overlay_url
        handler = _handler_class(self.state_store, self.overlay_path)
        self._server = _ReusableThreadingHTTPServer((self.host, self.port), handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, name="SongCreditManagerForOBSServer")
        self._thread.daemon = True
        self._thread.start()
        return self.overlay_url

    def stop(self):
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
