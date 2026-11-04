"""KML output for Google Earth Pro.

``/networklink.kml`` is the file you open once in Google Earth; it tells Google
Earth to re-fetch ``/live.kml`` every few seconds so the people move live.
"""

from __future__ import annotations

import math
import time
from xml.sax.saxutils import escape

from .positioning import M_PER_DEG_LAT, M_PER_DEG_LON_EQ

PALETTE = ["2563eb", "dc2626", "16a34a", "d97706", "9333ea", "0891b2", "db2777", "65a30d"]


def _kml_color(hex_rgb: str, alpha: str = "ff") -> str:
    """'#RRGGBB' -> KML 'AABBGGRR'."""
    h = hex_rgb.lstrip("#")
    return f"{alpha}{h[4:6]}{h[2:4]}{h[0:2]}"


def color_for(dev: dict) -> str:
    if dev.get("color"):
        return dev["color"].lstrip("#")
    return PALETTE[int(dev["mac"].replace(":", ""), 16) % len(PALETTE)]


def _circle(lat, lon, r_m, n=36):
    kx = M_PER_DEG_LON_EQ * math.cos(math.radians(lat))
    pts = []
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        pts.append(f"{lon + r_m * math.cos(a) / kx:.7f},{lat + r_m * math.sin(a) / M_PER_DEG_LAT:.7f},0")
    return " ".join(pts)


def live_kml(state: dict, map_cfg: dict, base_url: str) -> str:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             f"<name>Wi-Fi locations {time.strftime('%H:%M:%S')}</name>",
             '<Style id="ap"><IconStyle><scale>0.9</scale><Icon><href>'
             'http://maps.google.com/mapfiles/kml/shapes/target.png</href></Icon></IconStyle></Style>']

    fp = map_cfg.get("floorplan")
    if fp and fp.get("image") and fp.get("bounds"):
        (s, w), (n, e) = fp["bounds"]
        parts.append(
            "<GroundOverlay><name>Floor plan</name>"
            f"<color>{format(int(255 * fp.get('opacity', 0.7)), '02x')}ffffff</color>"
            f"<Icon><href>{escape(base_url)}/floorplan</href></Icon>"
            f"<LatLonBox><north>{max(s, n)}</north><south>{min(s, n)}</south>"
            f"<east>{max(w, e)}</east><west>{min(w, e)}</west>"
            f"<rotation>{fp.get('rotation', 0)}</rotation></LatLonBox></GroundOverlay>")

    parts.append("<Folder><name>Access points</name>")
    for ap in state["aps"]:
        parts.append(f'<Placemark><name>{escape(ap["name"])}</name><styleUrl>#ap</styleUrl>'
                     f'<Point><coordinates>{ap["lon"]},{ap["lat"]},0</coordinates></Point></Placemark>')
    parts.append("</Folder><Folder><name>People / devices</name>")

    for d in state["devices"]:
        c = color_for(d)
        heard = ", ".join(f"{k} {v} dBm" for k, v in d["aps_heard"].items())
        desc = (f"MAC {d['mac']}<br/>Nearest AP: {escape(d['nearest_ap'])} ({d['rssi']} dBm)<br/>"
                f"Heard by: {escape(heard)}<br/>Accuracy: ±{d['accuracy_m']} m<br/>"
                f"Last seen: {d['age_s']} s ago")
        parts.append(
            f'<Placemark><name>{escape(d["name"])}</name><description><![CDATA[{desc}]]></description>'
            f'<Style><IconStyle><color>{_kml_color(c)}</color><scale>1.1</scale><Icon><href>'
            'http://maps.google.com/mapfiles/kml/shapes/man.png</href></Icon></IconStyle>'
            f'<LabelStyle><scale>0.9</scale></LabelStyle></Style>'
            f'<Point><coordinates>{d["lon"]:.7f},{d["lat"]:.7f},0</coordinates></Point></Placemark>')
        parts.append(
            f'<Placemark><name>{escape(d["name"])} accuracy</name>'
            f'<Style><LineStyle><color>{_kml_color(c)}</color><width>1</width></LineStyle>'
            f'<PolyStyle><color>{_kml_color(c, "33")}</color></PolyStyle></Style>'
            f'<Polygon><outerBoundaryIs><LinearRing><coordinates>'
            f'{_circle(d["lat"], d["lon"], d["accuracy_m"])}'
            f'</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>')
    parts.append("</Folder></Document></kml>")
    return "".join(parts)


def network_link_kml(base_url: str, refresh_seconds: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <NetworkLink>
    <name>MikroTik Wi-Fi locator (live)</name>
    <flyToView>1</flyToView>
    <Link>
      <href>{escape(base_url)}/live.kml</href>
      <refreshMode>onInterval</refreshMode>
      <refreshInterval>{refresh_seconds}</refreshInterval>
    </Link>
  </NetworkLink>
</kml>
"""
