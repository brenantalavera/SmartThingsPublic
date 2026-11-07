# Ranch RF awareness / MikroTik Wi-Fi locator: working rules

Read `HANDOFF.md` (what to do, in order) and `PLAN.md` (why: feasibility, decisions, design) before changing anything.

## This session runs on the owner's server, on a live ranch network. Hard rules
1. **MikroTik devices are read-only for you.** Use only the read-only `locator` account. Never run commands that change
   router configuration (users, services, certificates, wireless/sniffer settings, firewall, upgrades, reboots).
   When a change is needed, write it as a `.rsc` file under `routeros/`, explain exactly what it does and on which device,
   and let the owner apply it. Get approval per device, every time.
2. **Never put a sniffer on a radio that serves users or carries a backhaul / point-to-point link.** Only on radios or units the
   owner has named as spare in writing (record it in `PLAN.md` §12.4).
3. **Passive only.** Don't send traffic to unknown or third-party devices: no deauth, no active probing, no port scans beyond
   the management network the owner names. Never try to identify strangers (no de-randomization or fingerprinting of who someone is).
   The red dot is the product. No IMSI/cellular anything.
4. **Secrets never go in git.** `config.toml`, inventory output and the database are git-ignored. Keep `config.toml` mode 600.
   Never echo passwords into logs or commit messages.
5. **Don't expose the web UI beyond the LAN/management network.** Keep basic auth on.
6. **Stand-down = silence the alarm only, never stop recording**, and never stand down if an unknown device is in the same zone (PLAN §9.3).

## Engineering rules
- Python 3.11+, standard library first. New dependencies need a reason (`librouteros` is optional already).
- Before every commit: `python3 -m unittest discover -s tests -t .`. After any positioning change: `python3 bench/accuracy.py`
  and compare with the table in PLAN §2.
- Work on branch `mikrotik-wifi-locator` (or a branch off it). Never push to `master`.
- Keep `PLAN.md` the source of truth: record decisions, owner answers and pilot results there as they happen.
- Try new behaviour in `--simulate` mode first; only then against HQ devices.

## Layout
- `locator/routeros.py`: REST/API polling of registration tables and DHCP leases
- `locator/positioning.py`: RSSI → distance → zone / weighted centroid
- `locator/server.py`: poll loop, web map, `/api/state`, KML for Google Earth, `/api/observations` for sensors
- `locator/simulate.py`: fake devices; `bench/accuracy.py`: accuracy benchmark
- `web/index.html`: Leaflet map (vendored, works offline except tiles)
- `routeros-setup.rsc`: creates the read-only `locator` user (owner runs it)
