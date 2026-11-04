"""Load and validate config.toml."""

from __future__ import annotations

import tomllib
from fnmatch import fnmatchcase as fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from .routeros import normalize_mac


@dataclass
class AccessPoint:
    name: str
    lat: float
    lon: float
    router: str = ""  # router name from [[routers]] ('' for sensors)
    interfaces: list[str] = field(default_factory=list)  # radios on that router
    sensor: str = ""  # id used by external sensors posting to /api/observations
    floor: int = 0
    rssi_at_1m: float | None = None
    path_loss_exponent: float | None = None


@dataclass
class Device:
    mac: str
    name: str
    color: str = ""
    owner: str = ""


@dataclass
class Config:
    path: Path
    routers: list[dict]
    aps: list[AccessPoint]
    devices: dict[str, Device]
    poll_seconds: float = 3.0
    window_seconds: float = 20.0
    stale_seconds: float = 300.0
    rssi_at_1m: float = -40.0
    path_loss_exponent: float = 3.0
    smoothing: float = 0.4
    track: str = "all"  # "all" or "known"
    host: str = "0.0.0.0"
    port: int = 8080
    username: str = ""
    password: str = ""
    sensor_token: str = ""
    map: dict = field(default_factory=dict)

    def ap_for(self, source: str, interface: str) -> AccessPoint | None:
        """Find which configured AP an observation came from."""
        for ap in self.aps:
            if ap.sensor and ap.sensor == source:
                return ap
            if ap.router == source and (
                    not ap.interfaces or any(fnmatch(interface, pat) for pat in ap.interfaces)):
                return ap
        return None


def load(path: str | Path) -> Config:
    path = Path(path)
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    pos = raw.get("positioning", {})
    srv = raw.get("server", {})
    aps = [AccessPoint(**ap) for ap in raw.get("aps", [])]
    if not aps:
        raise ValueError(f"{path}: at least one [[aps]] entry is required")
    router_names = {r["name"] for r in raw.get("routers", [])}
    for ap in aps:
        if not ap.sensor and ap.router not in router_names:
            raise ValueError(f"AP {ap.name!r}: router {ap.router!r} is not defined in [[routers]]")

    devices = {}
    for d in raw.get("devices", []):
        dev = Device(**d)
        dev.mac = normalize_mac(dev.mac)
        devices[dev.mac] = dev

    return Config(
        path=path,
        routers=raw.get("routers", []),
        aps=aps,
        devices=devices,
        poll_seconds=pos.get("poll_seconds", 3.0),
        window_seconds=pos.get("window_seconds", 20.0),
        stale_seconds=pos.get("stale_seconds", 300.0),
        rssi_at_1m=pos.get("rssi_at_1m", -40.0),
        path_loss_exponent=pos.get("path_loss_exponent", 3.0),
        smoothing=pos.get("smoothing", 0.4),
        track=pos.get("track", "all"),
        host=srv.get("host", "0.0.0.0"),
        port=srv.get("port", 8080),
        username=srv.get("username", ""),
        password=srv.get("password", ""),
        sensor_token=srv.get("sensor_token", ""),
        map=raw.get("map", {}),
    )
