"""Poll loop + small HTTP server (web map, JSON API, KML for Google Earth)."""

from __future__ import annotations

import base64
import hmac
import json
import logging
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import kml
from .config import Config
from .positioning import Locator
from .routeros import Observation, RouterOSError, normalize_mac

log = logging.getLogger("locator")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class App:
    def __init__(self, cfg: Config, sources: list):
        self.cfg = cfg
        self.sources = sources  # objects with .name? and .poll() -> [Observation]
        self.locator = Locator(cfg)
        self.lock = threading.Lock()
        self.errors: dict[str, str] = {}

    def poll_forever(self):
        while True:
            start = time.time()
            for src in self.sources:
                name = getattr(src, "name", "simulator")
                try:
                    obs = src.poll()
                    with self.lock:
                        self.locator.ingest(obs)
                        self.locator.hostnames.update(getattr(src, "hostnames", {}))
                    if self.errors.pop(name, None):
                        log.info("%s: reconnected", name)
                except RouterOSError as e:
                    if self.errors.get(name) != str(e):
                        log.warning("%s: %s", name, e)
                    self.errors[name] = str(e)
            time.sleep(max(0.2, self.cfg.poll_seconds - (time.time() - start)))

    def state(self) -> dict:
        with self.lock:
            s = self.locator.snapshot()
        s["errors"] = dict(self.errors)
        return s


def make_handler(app: App):
    cfg = app.cfg
    expected_auth = None
    if cfg.username:
        expected_auth = "Basic " + base64.b64encode(f"{cfg.username}:{cfg.password}".encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "WifiLocator/1.0"

        def log_message(self, fmt, *args):
            log.debug("%s " + fmt, self.address_string(), *args)

        def _send(self, code, body: bytes | str, ctype="application/json"):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not expected_auth:
                return True
            if hmac.compare_digest(self.headers.get("Authorization", ""), expected_auth):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="wifi-locator"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def _base_url(self):
            return f"http://{self.headers.get('Host', f'localhost:{cfg.port}')}"

        def do_GET(self):
            path = self.path.split("?")[0]
            if not self._authorized():
                return
            if path in ("/", "/index.html"):
                return self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._send(200, json.dumps(app.state()))
            if path == "/api/config":
                m = dict(cfg.map)
                if m.get("floorplan"):
                    m["floorplan"] = {**m["floorplan"], "url": "/floorplan"}
                return self._send(200, json.dumps({"map": m, "poll_seconds": cfg.poll_seconds}))
            if path == "/live.kml":
                return self._send(200, kml.live_kml(app.state(), cfg.map, self._base_url()),
                                  "application/vnd.google-earth.kml+xml")
            if path == "/networklink.kml":
                body = kml.network_link_kml(self._base_url(), max(2, int(cfg.poll_seconds)))
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.google-earth.kml+xml")
                self.send_header("Content-Disposition", 'attachment; filename="wifi-locator.kml"')
                self.send_header("Content-Length", str(len(body.encode())))
                self.end_headers()
                self.wfile.write(body.encode())
                return
            if path.startswith("/vendor/"):
                f = (WEB_DIR / path.lstrip("/")).resolve()
                if f.is_file() and WEB_DIR in f.parents:
                    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                    return self._send(200, f.read_bytes(), ctype)
            if path == "/floorplan":
                fp = (cfg.map.get("floorplan") or {}).get("image")
                if fp:
                    f = (cfg.path.parent / fp).resolve()
                    if f.is_file():
                        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                        return self._send(200, f.read_bytes(), ctype)
            self._send(404, '{"error":"not found"}')

        def do_POST(self):
            """External sensors (e.g. ESP32 probe-request sniffers) push readings here:
            POST /api/observations  {"sensor": "esp-garage", "readings": [{"mac": "..", "rssi": -61}]}
            """
            if self.path.split("?")[0] != "/api/observations":
                return self._send(404, '{"error":"not found"}')
            token = self.headers.get("X-Sensor-Token", "")
            if not cfg.sensor_token or not hmac.compare_digest(token, cfg.sensor_token):
                return self._send(403, '{"error":"bad or missing X-Sensor-Token"}')
            try:
                n = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(min(n, 1_000_000)))
                now = time.time()
                obs = [Observation(str(data["sensor"]), "", normalize_mac(r["mac"]), int(r["rssi"]), now)
                       for r in data["readings"]]
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, json.dumps({"error": str(e)}))
            with app.lock:
                app.locator.ingest(obs)
            self._send(200, json.dumps({"accepted": len(obs)}))

    return Handler


def serve(app: App):
    threading.Thread(target=app.poll_forever, daemon=True, name="poller").start()
    httpd = ThreadingHTTPServer((app.cfg.host, app.cfg.port), make_handler(app))
    log.info("Map:          http://%s:%d/", app.cfg.host, app.cfg.port)
    log.info("Google Earth: http://%s:%d/networklink.kml", app.cfg.host, app.cfg.port)
    httpd.serve_forever()
