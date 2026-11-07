# Handoff: build and pilot the ranch RF-awareness system at HQ

## Where things stand
- **Built and tested offline (cloud session, no real router):** `python -m locator` polls MikroTik RouterOS (REST v7, or classic
  API via `librouteros`), places connected Wi-Fi clients near their AP on a satellite/floor-plan map, and serves a live
  Google Earth layer. 8 unit tests pass. It was checked against a fake RouterOS over HTTPS, the web security matrix, a mobile UI and 300-client load.
  Accuracy was simulated (PLAN §2).
- **Never run against real MikroTik gear.** That's your first job.
- **Owner's goal:** a "red dot" layer to go with cameras and security drones on a large ranch with **hundreds of MikroTik devices**.
  Known people (crew, registered UPS/FedEx drivers) show as green/blue; unknown devices show amber/red by zone and time.
  **Building 90 = package delivery building**: crew arrival → alarm stand-down; UPS/FedEx arrival → notification.
  **Pilot site = HQ** ("117", meaning to confirm with the owner).
- Full reasoning, verified facts, risks and decisions: `PLAN.md`. Rules for working on the live network: `CLAUDE.md`.

## Before you start (owner does these, you help)
1. On the server: `git clone https://github.com/brenantalavera/SmartThingsPublic.git && cd SmartThingsPublic && git checkout mikrotik-wifi-locator && cd mikrotik-wifi-locator`
2. Python 3.11+ (`python3 --version`). Optional: `pip install librouteros` for RouterOS v6 / classic API.
3. The server must reach the MikroTik management addresses (ask the owner which subnet/VLAN).
4. Owner runs `routeros-setup.rsc` on the HQ test device(s) (or the CAPsMAN controller). It creates the read-only `locator` user.
   Owner sets the password and subnet. You may adjust the script, but the owner applies it.
5. `cp config.example.toml config.toml && chmod 600 config.toml`. The owner types in the password.

## Tasks, in order (each ends with tests passing, a commit, and PLAN.md updated)

### T0. Smoke test on one real device
- `python3 -m unittest discover -s tests -t .` then `python3 -m locator --once`.
- **Done when:** clients from HQ are listed with signal and interface. Any real-world difference from the assumptions in
  PLAN §3 (field names, error codes for missing menus or permissions, PLAN risk R4) is fixed in code, with a test, and noted in PLAN.

### T1. Read-only fleet inventory (PLAN §11 Step 0)
- New `locator/inventory.py` (`python3 -m locator.inventory`): for each device (list, or discovered via `/ip/neighbor`
  from the core), record identity, model/board, serial, RouterOS version, wireless package, radios/bands,
  whether each radio serves clients or is a backhaul/PtP link, sniffer capability, GPS, Bluetooth (KNOT), uptime and IP.
- Output: `data/inventory.csv` and `data/inventory.kml` (git-ignored). Concurrent, with timeouts; one dead device must not stall the run.
- **Done when:** run against HQ, the owner reviews the CSV, and spare/sniffer-candidate radios are marked by the owner in PLAN §12.4.

### T2. Scale the poller (PLAN §11 gaps)
- Concurrent polling with per-router back-off; CAPsMAN-controller mode.
- Bulk import of AP positions from KML (Google Earth pins named by identity), CSV, or inventory GPS.
- A sensor-health panel: offline AP = blind spot, shown on the map. Marker clustering. Trails off by default in `/api/state`.
- **Done when:** all HQ APs are on the map from an import, and a simulated 300-router fleet polls within one interval.

### T3. Roles, zones, rules, stand-down, event log (PLAN §9)
- Roles: crew/family (green), delivery (blue), visitor with expiry (purple), unknown (amber/red), own drones/vehicles (grey).
  Assigned from config and from DHCP lease comments (e.g. `UPS – route 12`).
- Zones (sensor sets, optional polygons) and rules by zone × hours × role, as in the PLAN §9.2 sketch. Building 90 rules included.
- Safe stand-down (PLAN §9.3). Event log in SQLite under `data/` with arrival/departure; delivery log; daily HTML report.
- Notification interface (start with a webhook + log; SmartThings/HA/SMS adapters later, as the owner chooses).
- **Done when:** unit tests cover every §9.3 case (crew alone → stand-down; crew + unknown → red; after-hours unknown at
  Building 90 → red; business-hours unknown at Building 90 → amber; registered UPS → notify).

### T4. Sensor sources for devices not on the Wi-Fi (PLAN §7, §10)
- **TZSP receiver** (UDP 37008) for MikroTik sniffer streams: parse 802.11 management frames (probe requests) and the signal
  field; feed observations to the locator as `sensor = <identity>`. Write fixtures from a real capture as soon as one exists.
- **Kismet source**: poll the Kismet REST API for devices plus signal per datasource.
- Unknown-device handling: an RSSI threshold per sensor, persistence (N sightings in M minutes), a baseline list learned over a week,
  and grouping of short-lived random MACs into one "unknown presence" per zone.
- **Done when:** both sources work against recorded/fixture data, and in a simulated demo red dots appear only per the rules.

### T5. Simulated demo for owner sign-off
- Extend `--simulate`: HQ layout, crew arriving at Building 90, a UPS driver (registered) and a FedEx driver (not registered),
  an after-hours stranger, and crew + stranger together. Screenshots and a 1-page summary for the owner.
- **Done when:** the owner signs off on the behaviour (record it in PLAN).

### T6. HQ pilot, steps A–F (PLAN §12.2)
Run with the owner on site, record the results in PLAN §12.3 and write the rollout recommendation.

## Open questions to ask the owner early
- What "117" refers to; the HQ device list; CAPsMAN/The Dude in use; RouterOS versions (any v6?); the management VLAN.
- Which HQ radios/units are spare (no clients, no backhaul) for sniffing.
- Crew shift hours, carriers, alert recipients and channel, camera VMS and drone platform (for later integration).
- Property boundary KML, and the locations of Building 90, HQ, gates and camera poles.
