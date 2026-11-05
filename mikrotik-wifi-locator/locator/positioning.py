"""Turn per-AP signal readings into estimated positions.

Method
------
1. RSSI -> distance with the log-distance path-loss model:
       d = 10 ** ((RSSI_1m - RSSI) / (10 * n))
2. Readings older than ``window_seconds`` are discarded.
3. One AP heard the device  -> it is "near that AP", radius = d.
   Two or more              -> weighted centroid (weights 1/d^2). Optional
                               least-squares trilateration (method="trilaterate")
                               tested worse with real-world-like noise and walls.
4. The result is smoothed with an exponential moving average.

All maths is done in a local flat metre grid centred on the APs, which is
accurate to well under a centimetre over a building-sized area.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import deque
from dataclasses import dataclass, field

from .config import AccessPoint, Config
from .routeros import Observation

M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LON_EQ = 111_320.0
MIN_DIST_M = 0.5
MAX_DIST_M = 60.0


class LocalGrid:
    def __init__(self, aps: list[AccessPoint]):
        self.lat0 = sum(a.lat for a in aps) / len(aps)
        self.lon0 = sum(a.lon for a in aps) / len(aps)
        self.kx = M_PER_DEG_LON_EQ * math.cos(math.radians(self.lat0))

    def to_xy(self, lat, lon):
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * M_PER_DEG_LAT

    def to_latlon(self, x, y):
        return self.lat0 + y / M_PER_DEG_LAT, self.lon0 + x / self.kx


def rssi_to_distance(rssi: float, rssi_at_1m: float, n: float) -> float:
    d = 10 ** ((rssi_at_1m - rssi) / (10 * n))
    return min(max(d, MIN_DIST_M), MAX_DIST_M)


def trilaterate(points: list[tuple[float, float, float]], iterations: int = 20,
                centroid_only: bool = False):
    """Least-squares fit of (x, y) to circles [(x_i, y_i, r_i), ...].

    Gauss-Newton on residuals |p - c_i| - r_i, weighted by 1/r_i so that
    near (more reliable) readings dominate. Starts at the weighted centroid.
    """
    w = [1 / (r * r) for _, _, r in points]
    sw = sum(w)
    x = sum(wi * px for wi, (px, _, _) in zip(w, points)) / sw
    y = sum(wi * py for wi, (_, py, _) in zip(w, points)) / sw
    if len(points) < 3 or centroid_only:
        return x, y

    def cost(cx, cy):
        return sum((math.hypot(cx - px, cy - py) - r) ** 2 / r for px, py, r in points)

    # Levenberg-Marquardt: damped Gauss-Newton that only accepts steps which
    # reduce the error, so noisy / inconsistent circles can't blow it up.
    lam, c = 1.0, cost(x, y)
    for _ in range(iterations):
        jtj = [[lam, 0.0], [0.0, lam]]
        jtr = [0.0, 0.0]
        for px, py, r in points:
            dx, dy = x - px, y - py
            dist = math.hypot(dx, dy) or 1e-6
            res = dist - r
            jx, jy = dx / dist, dy / dist
            wt = 1 / r
            jtj[0][0] += wt * jx * jx
            jtj[0][1] += wt * jx * jy
            jtj[1][1] += wt * jy * jy
            jtr[0] += wt * jx * res
            jtr[1] += wt * jy * res
        det = jtj[0][0] * jtj[1][1] - jtj[0][1] ** 2
        sx = (jtj[1][1] * jtr[0] - jtj[0][1] * jtr[1]) / det
        sy = (jtj[0][0] * jtr[1] - jtj[0][1] * jtr[0]) / det
        step = math.hypot(sx, sy)
        if step > 3.0:  # never jump more than 3 m per iteration
            sx, sy = sx * 3.0 / step, sy * 3.0 / step
        nc = cost(x - sx, y - sy)
        if nc < c:
            x, y, c, lam = x - sx, y - sy, nc, lam * 0.3
            if step < 0.01:
                break
        else:
            lam *= 10
            if lam > 1e6:
                break
    # Keep the answer inside the area the APs can plausibly cover.
    pad = min(r for *_, r in points)
    x = min(max(x, min(p[0] for p in points) - pad), max(p[0] for p in points) + pad)
    y = min(max(y, min(p[1] for p in points) - pad), max(p[1] for p in points) + pad)
    return x, y


@dataclass
class Reading:
    ap: AccessPoint
    rssi: int
    ts: float
    distance: float


@dataclass
class Track:
    mac: str
    readings: dict[str, Reading] = field(default_factory=dict)  # by AP name
    x: float | None = None
    y: float | None = None
    accuracy: float = 0.0
    last_seen: float = 0.0
    trail: deque = field(default_factory=lambda: deque(maxlen=200))
    ssid: str = ""
    band: str = ""


def _jitter(mac: str, radius: float) -> tuple[float, float]:
    """Stable small offset so several devices on one AP don't overlap exactly."""
    h = int(hashlib.sha1(mac.encode()).hexdigest()[:8], 16)
    angle = (h % 3600) / 3600 * 2 * math.pi
    return radius * math.cos(angle), radius * math.sin(angle)


class Locator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.grid = LocalGrid(cfg.aps)
        self.tracks: dict[str, Track] = {}
        self.hostnames: dict[str, str] = {}
        self.unmapped: dict[str, float] = {}  # "router/interface" with no [[aps]] match

    def ingest(self, observations: list[Observation]):
        cfg = self.cfg
        touched = set()
        for o in observations:
            if cfg.track == "known" and o.mac not in cfg.devices:
                continue
            ap = cfg.ap_for(o.source, o.interface)
            if ap is None:
                self.unmapped[f"{o.source}/{o.interface}"] = o.ts
                continue
            p0 = ap.rssi_at_1m if ap.rssi_at_1m is not None else cfg.rssi_at_1m
            n = ap.path_loss_exponent or cfg.path_loss_exponent
            t = self.tracks.setdefault(o.mac, Track(o.mac))
            prev = t.readings.get(ap.name)
            # One AP can report a client on two radios; keep the stronger one.
            if prev and prev.ts == o.ts and prev.rssi >= o.rssi:
                continue
            t.readings[ap.name] = Reading(ap, o.rssi, o.ts, rssi_to_distance(o.rssi, p0, n))
            t.last_seen = max(t.last_seen, o.ts)
            t.ssid, t.band = o.ssid or t.ssid, o.band or t.band
            touched.add(o.mac)
        for mac in touched:
            self._update(self.tracks[mac])

    def _update(self, t: Track):
        cutoff = t.last_seen - self.cfg.window_seconds
        t.readings = {k: r for k, r in t.readings.items() if r.ts >= cutoff}
        rs = list(t.readings.values())
        pts = [(*self.grid.to_xy(r.ap.lat, r.ap.lon), r.distance) for r in rs]
        if len(pts) == 1:
            ax, ay, d = pts[0]
            jx, jy = _jitter(t.mac, min(2.0, d / 3))
            x, y, acc = ax + jx, ay + jy, d
        else:
            x, y = trilaterate(pts, centroid_only=self.cfg.method != "trilaterate")
            resid = [abs(math.hypot(x - px, y - py) - r) for px, py, r in pts]
            acc = max(1.0, math.sqrt(sum(e * e for e in resid) / len(resid)) +
                      min(r for *_, r in pts) / 2)
        a = self.cfg.smoothing
        if t.x is None:
            t.x, t.y = x, y
        else:
            t.x, t.y = a * x + (1 - a) * t.x, a * y + (1 - a) * t.y
        t.accuracy = acc if t.accuracy == 0 else a * acc + (1 - a) * t.accuracy
        lat, lon = self.grid.to_latlon(t.x, t.y)
        if not t.trail or math.hypot(t.trail[-1][3] - t.x, t.trail[-1][4] - t.y) > 1.0:
            t.trail.append((lat, lon, t.last_seen, t.x, t.y))

    def snapshot(self) -> dict:
        now = time.time()
        out = []
        for mac, t in list(self.tracks.items()):
            if t.x is None:
                continue
            age = now - t.last_seen
            if age > self.cfg.stale_seconds:
                continue
            dev = self.cfg.devices.get(mac)
            lat, lon = self.grid.to_latlon(t.x, t.y)
            best = max(t.readings.values(), key=lambda r: r.rssi, default=None)
            out.append({
                "mac": mac,
                "name": dev.name if dev else self.hostnames.get(mac, mac),
                "owner": dev.owner if dev else "",
                "color": dev.color if dev else "",
                "known": dev is not None,
                "lat": lat,
                "lon": lon,
                "accuracy_m": round(t.accuracy, 1),
                "floor": best.ap.floor if best else 0,
                "nearest_ap": best.ap.name if best else "",
                "rssi": best.rssi if best else None,
                "aps_heard": {r.ap.name: r.rssi for r in t.readings.values()},
                "ssid": t.ssid,
                "band": t.band,
                "last_seen": t.last_seen,
                "age_s": round(age),
                "trail": [[p[0], p[1]] for p in t.trail],
            })
        out.sort(key=lambda d: (not d["known"], d["name"].lower()))
        return {
            "updated": now,
            "aps": [{"name": a.name, "lat": a.lat, "lon": a.lon, "floor": a.floor}
                    for a in self.cfg.aps],
            "devices": out,
            "unmapped_interfaces": sorted(self.unmapped),
        }
