"""Read Wi-Fi client signal data from MikroTik RouterOS.

Supports the RouterOS v7 REST API (no extra dependencies) and, optionally, the
classic binary API on port 8728/8729 via the ``librouteros`` package, which also
works on RouterOS v6.

Every wireless stack RouterOS has shipped is handled:

* ``/interface/wifi``        - RouterOS 7.13+ "wifi" package (incl. CAPsMAN v2)
* ``/interface/wifiwave2``   - older RouterOS 7 wifiwave2 package
* ``/caps-man``              - legacy CAPsMAN controller
* ``/interface/wireless``    - legacy standalone wireless
"""

from __future__ import annotations

import base64
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

REGISTRATION_TABLES = [
    "interface/wifi/registration-table",
    "interface/wifiwave2/registration-table",
    "caps-man/registration-table",
    "interface/wireless/registration-table",
]
DHCP_LEASES = "ip/dhcp-server/lease"

# Field names that carry the client's signal as heard by the AP, by stack.
SIGNAL_FIELDS = ("signal", "rx-signal", "signal-strength")
_INT_RE = re.compile(r"-?\d+")


@dataclass
class Observation:
    """One AP (or sensor) hearing one client at a given signal level."""

    source: str  # router name or sensor id from the config
    interface: str  # radio interface on that router ('' for sensors)
    mac: str
    rssi: int  # dBm
    ts: float
    ssid: str = ""
    band: str = ""


def parse_signal(value) -> int | None:
    """'-62', '-62@6Mbps' or '-62dBm' -> -62."""
    if value is None:
        return None
    m = _INT_RE.search(str(value))
    return int(m.group()) if m else None


def normalize_mac(mac: str) -> str:
    return mac.strip().upper().replace("-", ":")


class RouterOSError(Exception):
    pass


class RestClient:
    """Minimal RouterOS v7 REST client using only the standard library."""

    def __init__(self, host, username, password, port=None, https=True,
                 verify_tls=True, timeout=5.0):
        scheme = "https" if https else "http"
        port = port or (443 if https else 80)
        self.base = f"{scheme}://{host}:{port}/rest/"
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self.timeout = timeout
        self.ctx = None
        if https:
            self.ctx = ssl.create_default_context()
            if not verify_tls:  # RouterOS often uses a self-signed certificate
                self.ctx.check_hostname = False
                self.ctx.verify_mode = ssl.CERT_NONE

    def get(self, path: str) -> list[dict]:
        req = urllib.request.Request(self.base + path, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            # 400/404 = that menu does not exist on this router (package not installed)
            if e.code in (400, 404):
                raise LookupError(path) from e
            raise RouterOSError(f"{path}: HTTP {e.code}") from e
        except (urllib.error.URLError, OSError) as e:
            raise RouterOSError(f"{path}: {e}") from e
        return data if isinstance(data, list) else [data]


class ApiClient:
    """Classic RouterOS API (v6 and v7) via the optional ``librouteros`` package."""

    def __init__(self, host, username, password, port=None, https=False,
                 verify_tls=True, timeout=5.0):
        try:
            import librouteros
        except ImportError as e:
            raise RouterOSError("mode='api' needs: pip install librouteros") from e
        kwargs = dict(host=host, username=username, password=password, timeout=timeout)
        if https:
            ctx = ssl.create_default_context()
            if not verify_tls:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl_wrapper"] = ctx.wrap_socket
            kwargs["port"] = port or 8729
        else:
            kwargs["port"] = port or 8728
        self._lib = librouteros
        self._kwargs = kwargs
        self._api = None

    def get(self, path: str) -> list[dict]:
        try:
            if self._api is None:
                self._api = self._lib.connect(**self._kwargs)
            return [dict(row) for row in self._api.path(*path.split("/"))]
        except self._lib.exceptions.TrapError as e:
            raise LookupError(path) from e
        except Exception as e:  # connection dropped: reconnect next poll
            self._api = None
            raise RouterOSError(f"{path}: {e}") from e


class Router:
    """One RouterOS device (a standalone AP or a CAPsMAN controller)."""

    def __init__(self, name, host, username, password, mode="rest", port=None,
                 https=True, verify_tls=True, tables="auto"):
        self.name = name
        cls = RestClient if mode == "rest" else ApiClient
        self.client = cls(host, username, password, port=port, https=https,
                          verify_tls=verify_tls)
        self.tables = list(REGISTRATION_TABLES) if tables == "auto" else list(tables)
        self.hostnames: dict[str, str] = {}
        self._last_lease_fetch = 0.0

    def poll(self) -> list[Observation]:
        now = time.time()
        obs: list[Observation] = []
        for table in list(self.tables):
            try:
                rows = self.client.get(table)
            except LookupError:
                # Not present on this router; stop asking for it.
                self.tables.remove(table)
                continue
            for row in rows:
                mac = row.get("mac-address")
                rssi = next((parse_signal(row[f]) for f in SIGNAL_FIELDS if f in row), None)
                if not mac or rssi is None:
                    continue
                obs.append(Observation(
                    source=self.name,
                    interface=row.get("interface", ""),
                    mac=normalize_mac(mac),
                    rssi=rssi,
                    ts=now,
                    ssid=row.get("ssid", ""),
                    band=row.get("band", ""),
                ))
        if now - self._last_lease_fetch > 60:
            self._refresh_hostnames()
            self._last_lease_fetch = now
        return obs

    def _refresh_hostnames(self):
        try:
            for lease in self.client.get(DHCP_LEASES):
                mac = lease.get("mac-address")
                name = lease.get("comment") or lease.get("host-name")
                if mac and name:
                    self.hostnames[normalize_mac(mac)] = name
        except (LookupError, RouterOSError):
            pass  # this router may not run the DHCP server
