import math
import time
import unittest
from pathlib import Path
from unittest import mock

from locator import config as config_mod
from locator.kml import live_kml
from locator.positioning import Locator, rssi_to_distance, trilaterate
from locator.routeros import Observation, Router, parse_signal

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


class SignalParsing(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_signal("-62"), -62)
        self.assertEqual(parse_signal("-62@6Mbps"), -62)  # legacy wireless
        self.assertEqual(parse_signal("-71dBm"), -71)
        self.assertIsNone(parse_signal(None))


class Maths(unittest.TestCase):
    def test_distance_model(self):
        self.assertAlmostEqual(rssi_to_distance(-40, -40, 3), 1.0)
        self.assertAlmostEqual(rssi_to_distance(-70, -40, 3), 10.0)

    def test_trilaterate_exact(self):
        target = (3.0, 4.0)
        aps = [(0, 0), (10, 0), (0, 10), (10, 10)]
        pts = [(x, y, math.hypot(target[0] - x, target[1] - y)) for x, y in aps]
        x, y = trilaterate(pts)
        self.assertAlmostEqual(x, 3.0, places=2)
        self.assertAlmostEqual(y, 4.0, places=2)


    def test_trilaterate_noisy_never_diverges(self):
        import random
        rnd = random.Random(0)
        aps = [(3, 3), (9, 9), (15, 3), (3, 9), (15, 9), (9, 3)]
        for _ in range(2000):
            k = rnd.randint(3, 6)
            pts = [(x, y, rnd.uniform(0.5, 40)) for x, y in rnd.sample(aps, k)]
            x, y = trilaterate(pts)
            self.assertTrue(-40 < x < 60 and -40 < y < 50, (pts, x, y))


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.cfg = config_mod.load(EXAMPLE)
        self.cfg.smoothing = 1.0

    def test_single_ap_places_device_near_it(self):
        loc = Locator(self.cfg)
        loc.ingest([Observation("main", "cap-wifi3", "12:34:56:78:9A:BC", -55, time.time())])
        d = loc.snapshot()["devices"][0]
        self.assertEqual(d["name"], "Brenan's phone")
        self.assertEqual(d["nearest_ap"], "Garage")
        garage = next(a for a in self.cfg.aps if a.name == "Garage")
        self.assertLess(abs(d["lat"] - garage.lat), 3e-5)

    def test_unmapped_interface_reported(self):
        loc = Locator(self.cfg)
        loc.ingest([Observation("main", "wlan-mystery", "AA:BB:CC:DD:EE:FF", -50, time.time())])
        self.assertEqual(loc.snapshot()["unmapped_interfaces"], ["main/wlan-mystery"])

    def test_kml_is_well_formed(self):
        import xml.dom.minidom
        loc = Locator(self.cfg)
        loc.ingest([Observation("main", "wifi1", "AA:BB:CC:DD:EE:FF", -60, time.time())])
        xml.dom.minidom.parseString(live_kml(loc.snapshot(), self.cfg.map, "http://x:8080"))


class RouterParsing(unittest.TestCase):
    def test_reads_each_stack_and_dhcp_names(self):
        tables = {
            "interface/wifi/registration-table": [
                {"interface": "cap-wifi1", "mac-address": "aa:bb:cc:00:00:01", "signal": "-58"}],
            "caps-man/registration-table": [
                {"interface": "cap2", "mac-address": "aa:bb:cc:00:00:02", "rx-signal": "-66"}],
            "interface/wireless/registration-table": [
                {"interface": "wlan1", "mac-address": "aa:bb:cc:00:00:03", "signal-strength": "-71@6Mbps"}],
            "ip/dhcp-server/lease": [{"mac-address": "aa:bb:cc:00:00:01", "host-name": "pixel"}],
        }

        def fake_get(path):
            if path not in tables:
                raise LookupError(path)
            return tables[path]

        r = Router("main", "h", "u", "p")
        with mock.patch.object(r.client, "get", side_effect=fake_get):
            obs = r.poll()
        self.assertEqual({(o.mac, o.rssi) for o in obs},
                         {("AA:BB:CC:00:00:01", -58), ("AA:BB:CC:00:00:02", -66),
                          ("AA:BB:CC:00:00:03", -71)})
        self.assertNotIn("interface/wifiwave2/registration-table", r.tables)
        self.assertEqual(r.hostnames["AA:BB:CC:00:00:01"], "pixel")


if __name__ == "__main__":
    unittest.main()
