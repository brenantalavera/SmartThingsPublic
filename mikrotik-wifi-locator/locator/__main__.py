"""python -m locator [-c config.toml] [--simulate] [--once]"""

import argparse
import logging
import sys

from . import config as config_mod
from .routeros import Router
from .server import App, serve
from .simulate import Simulator


def main(argv=None):
    p = argparse.ArgumentParser(prog="locator", description=__doc__)
    p.add_argument("-c", "--config", default="config.toml")
    p.add_argument("--simulate", action="store_true",
                   help="use fake walking devices instead of the routers (UI demo)")
    p.add_argument("--once", action="store_true",
                   help="poll the routers once, print what was seen, and exit (setup check)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    cfg = config_mod.load(a.config)
    if a.simulate:
        sources = [Simulator(cfg)]
    else:
        sources = []
        for r in cfg.routers:
            r = dict(r)
            sources.append(Router(r.pop("name"), r.pop("host"), r.pop("username"),
                                  r.pop("password"), **r))

    if a.once:
        for src in sources:
            obs = src.poll()
            print(f"== {getattr(src, 'name', 'simulator')}: {len(obs)} client(s)")
            for o in obs:
                ap = cfg.ap_for(o.source, o.interface)
                print(f"  {o.mac}  {o.rssi:>4} dBm  iface={o.interface:<14} "
                      f"-> AP {ap.name if ap else '!! NOT MAPPED - add this interface to an [[aps]] entry'}")
        return 0

    serve(App(cfg, sources))


if __name__ == "__main__":
    sys.exit(main())
