"""Fake Wi-Fi clients walking around your configured APs, for trying the UI
without a router (``python -m locator --simulate``)."""

from __future__ import annotations

import math
import random
import time

from .config import Config, Device
from .positioning import LocalGrid
from .routeros import Observation

FAKE = [("AA:00:00:00:00:01", "Alex's phone"), ("AA:00:00:00:00:02", "Sam's phone"),
        ("AA:00:00:00:00:03", "Jordan's laptop"), ("AA:00:00:00:00:04", "Kitchen tablet"),
        ("AA:00:00:00:00:05", "Riley's watch")]


class Simulator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.grid = LocalGrid(cfg.aps)
        xy = [self.grid.to_xy(a.lat, a.lon) for a in cfg.aps]
        pad = 6
        self.box = (min(p[0] for p in xy) - pad, max(p[0] for p in xy) + pad,
                    min(p[1] for p in xy) - pad, max(p[1] for p in xy) + pad)
        self.walkers = []
        for mac, name in FAKE:
            self.walkers.append({"mac": mac, "pos": self._rand(), "goal": self._rand(),
                                 "speed": random.uniform(0.3, 1.2), "assoc": None})
            cfg.devices.setdefault(mac, Device(mac, name))
        self.t = time.time()

    def _rand(self):
        x0, x1, y0, y1 = self.box
        return [random.uniform(x0, x1), random.uniform(y0, y1)]

    def poll(self) -> list[Observation]:
        now = time.time()
        dt, self.t = now - self.t, now
        obs = []
        for w in self.walkers:
            dx, dy = w["goal"][0] - w["pos"][0], w["goal"][1] - w["pos"][1]
            dist = math.hypot(dx, dy)
            step = w["speed"] * dt
            if dist < step or random.random() < 0.01:
                w["goal"] = self._rand()
            else:
                w["pos"][0] += dx / dist * step
                w["pos"][1] += dy / dist * step
            # Signal each AP would hear, with real-world-ish noise.
            sig = {}
            for ap in self.cfg.aps:
                ax, ay = self.grid.to_xy(ap.lat, ap.lon)
                d = max(0.5, math.hypot(w["pos"][0] - ax, w["pos"][1] - ay))
                sig[ap.name] = (ap, round(self.cfg.rssi_at_1m - 10 * self.cfg.path_loss_exponent
                                          * math.log10(d) + random.gauss(0, 3)))
            # Clients stay on their AP until another is 6 dB better (sticky roaming),
            # and only the AP they are associated with reports them - like RouterOS.
            best = max(sig, key=lambda k: sig[k][1])
            if w["assoc"] is None or sig[best][1] > sig[w["assoc"]][1] + 6:
                w["assoc"] = best
            ap, rssi = sig[w["assoc"]]
            src = ap.sensor or ap.router
            iface = ap.interfaces[0] if ap.interfaces else ""
            obs.append(Observation(src, iface, w["mac"], rssi, now, "HomeWiFi", "5ghz-ax"))
        return obs
