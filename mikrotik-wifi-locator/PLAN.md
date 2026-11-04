# Wi-Fi people-location on MikroTik: feasibility report and plan

Status: **prototype built and tested offline. Not yet run against a real router.**
Handoff note: the code in this folder works end to end in simulation. This document records
what was verified, what wasn't, what the numbers say, and the plan for the next session.

---

## 1. Verdict

| Goal | Feasible? | With what |
|---|---|---|
| Who is home / away | **Yes, reliable** | Any MikroTik AP, no extra hardware |
| Which AP a person is connected to, shown on a map | **Yes** | Stock MikroTik. This is what the prototype does today |
| Which **room** a person is in | **Only with extra sensors** | Stock gear picks the right room about 40% of the time, even with 1 AP per room. Extra listening sensors raise that to about 70–75% |
| Position within about 2 m | **Not realistic with Wi-Fi signal strength** | Best simulated case: median 2.0 m, 90th percentile 3.5 m |
| Map overlay (satellite or own floor plan) and Google Earth | **Yes** | Done in the prototype |

**Why stock MikroTik tops out at "which AP":** RouterOS reports a client's signal only on the
AP the client is *connected to*. No RouterOS API exposes how strongly *other* APs hear the
client. This was confirmed against the RouterOS manual and the mktxp and Home Assistant
integrations. Phones also stay connected to an AP long after walking away from it (sticky
roaming), so "connected AP" is a weak stand-in for "current room".

---

## 2. What was tested (all passing)

| Area | How | Result |
|---|---|---|
| Unit tests (8) | `python3 -m unittest discover -s tests -t .` | Pass |
| REST client, real HTTPS | Fake RouterOS server: self-signed TLS, Basic auth, one fake router per wireless package | 16/16 pass. Parses `wifi` (`signal`), CAPsMAN (`rx-signal`) and legacy (`signal-strength` `-73@6Mbps`). Auto-detects the menu, uses the DHCP lease comment as the name, gives clear errors for bad password / unreachable / timeout / untrusted certificate |
| Classic API (`librouteros` 4.2.2) | Checked the real library signature, did a TLS handshake against the fake router | Works. **Bug found and fixed:** TLS with certificate checking on would always fail (hostname not passed) |
| Web server security | curl matrix | 401 without or with wrong login, 200 with login; path traversal (plain and `%2e%2e`) → 404; sensor endpoint → 403 without token, 400 for bad JSON or missing field |
| KML / Google Earth | Parsed the output; placemarks, accuracy circles and floor-plan ground overlay present | Valid XML. **Not opened in actual Google Earth Pro** (see risks) |
| Web UI | Headless Chromium: desktop, iPhone 13 in dark mode | No JS errors, no sideways scroll, list and popup work, floor plan draws |
| Load | 300 clients × 100 polls | 5 ms per poll. `/api/state` is 1.1 MB with trails (see backlog) |
| Accuracy | Simulated house (below) | **Bug found and fixed:** trilateration diverged to km-scale errors once 3+ APs heard a device. Also switched the default method to weighted centroid, which measured better |

**Not tested (no access from the build sandbox):** a real RouterOS device or CHR
(MikroTik downloads are blocked there), the satellite and street tile servers, Google Earth Pro itself, and the
`routeros-setup.rsc` script on a real router (syntax was checked against the manual only).

### Accuracy study (`python3 bench/accuracy.py`)

Simulated house: 18 × 12 m, 6 rooms. Walls cost 4 dB each, signal noise 4 dB slow + 2 dB fast,
and the calibration is deliberately off (true n=3.3, P0=−42; configured 3.0, −40). Averaged over 8 seeded walks.

| APs | Stock MikroTik (connected AP only) | + sensors that hear every device |
|---|---|---|
| 1 | 4.3 m median · 24% right room | same |
| 2 | 3.7 m · 27% | 3.0 m · 38% |
| 3 | 3.7 m · 38% | 2.7 m · 51% |
| 4 | 3.5 m · 41% | 2.2 m · 67% |
| 6 (1 per room) | 3.5 m · 40% | **2.0 m · 74%** |

A random guess picks the right room 17% of the time. Weighted centroid beat least-squares
trilateration in every multi-AP case (e.g. 2.0 m vs 3.2 m with 6). Trilateration is still available as `method = "trilaterate"`.
Caveat: the "sensors hear everything" column is optimistic (see risk R1).

---

## 3. Facts verified against docs/source

- REST API: `https://<router>/rest/<menu>`, Basic auth, RouterOS ≥ 7.1. All values are returned as strings.
- User group needs `read,api,rest-api` (REST logs in through the API internally). `/user add ... address=<subnet>` restricts where the user can log in from.
- Signal fields: `/interface/wifi` and `wifiwave2` → `signal`; legacy CAPsMAN → `rx-signal`; legacy wireless → `signal-strength` (`-74dBm@6Mbps`). The code handles all of them.
- CAPsMAN (wifi, 7.13+): the controller's registration table lists clients of *all* CAPs, on interfaces named `cap-wifiN` by default. So one router poll covers the whole house.
- librouteros converts values (it returns `signal` as an int). Handled.
- RouterOS sniffer / snooper are not usable in production: they take the radio out of service, and there is no API output.
- Phone MACs: iOS 18+ uses a *fixed* private MAC on WPA2/3 networks; Android uses a persistent per-network random MAC. So MAC → person mapping is stable on a home network.

---

## 4. Risks and open questions

- **R1. Extra sensors are harder than they look.** Connected phones rarely send probe requests,
  so a sensor must capture the phone's *data frames* on the channel its AP uses. Classic ESP32
  boards are **2.4 GHz only** and won't hear phones on 5 GHz. Options: ESP32-C5 (dual-band, newer), a Raspberry Pi with
  a monitor-mode USB adapter, or steering phones to 2.4 GHz (bad trade). **This needs a small hardware prototype before anyone commits.**
- **R2. Proven alternative for room-level presence: BLE.** Projects like ESPresense (ESP32 per
  room) or Home Assistant's Bermuda integration track phones and watches over Bluetooth
  through a companion app. They routinely reach room-level accuracy and could feed this map through `/api/observations`.
  Worth weighing against Wi-Fi sniffing.
- R3. Google Earth Pro with HTTP Basic auth on the network link is unverified. Fallback: a token in the URL query string.
- R4. Real RouterOS error codes for a missing menu or missing permission are unverified. The code assumes 400/404 means "menu not on this router" and stops polling it. A permission error that returns 400 would silently disable a table, so log it instead.
- R5. Privacy and legal: live location of household members. Keep auth on, keep it LAN-only, and tell people.

## 5. Decisions needed from the owner

1. Hardware inventory: how many MikroTik APs, which models, RouterOS version, CAPsMAN or not? (This sets the stock accuracy.)
2. Is "which AP / zone + home/away" enough, or is room-level a must? If it's a must, choose sensors: Wi-Fi sniffers (R1) or BLE (R2).
3. Where it runs: Pi, NAS, or Docker host?
4. Map: satellite, or your own floor plan (provide an image)?
5. Integrations wanted: SmartThings / Home Assistant presence, history and heatmaps?

---

## 6. Plan

**Phase 0 – Validate on the real network (1 session, owner present)**
1. Run `routeros-setup.rsc` on the router, check `/rest` with curl.
2. `python -m locator --once`: confirm the field names, interface names, and that DHCP names show up.
3. Place the APs, calibrate `rssi_at_1m` / `path_loss_exponent`, walk the house, and record actual room-hit-rate.
4. Open `/networklink.kml` in Google Earth Pro (R3).
Exit criteria: live map shows household phones near the correct AP.

**Phase 1 – Harden (code)**
- Log permission errors separately from missing menus (R4).
- Add a `?trails=1` option so trails are only sent on request (state is 1.1 MB at 300 clients).
- Show unmapped sensors properly in the UI (it currently prints a trailing `esp-hall/`); spread out overlapping labels.
- Persist history (SQLite) and add a time-slider replay. Add a `Dockerfile` / systemd unit.
- Re-run `bench/accuracy.py` after any positioning change.

**Phase 2 – Better "room" with stock gear (cheap, try first)**
- Map zones to APs (polygons drawn on the floor plan) instead of points.
- Enable `/interface/wifi/steering` (802.11k/v) and tune the roaming thresholds so phones roam sooner, then re-measure the room-hit-rate.

**Phase 3 – Room-level (only if needed; prototype first)**
- Prototype one sensor (ESP32-C5 or Pi + monitor adapter, *or* ESPresense BLE). Measure how often it hears a connected phone on 5 GHz.
- If it works, deploy one per room, posting to `/api/observations`. Expect about 2 m median and about 70% right room.

**Phase 4 – Integrations (optional)**
- Publish presence and room to SmartThings / Home Assistant (MQTT); geofence automations.

---

## 7. Extension: detecting devices that are NOT on the Wi-Fi (security mode)

Owner's goal: detect phones and devices of anyone on the property, including people not
connected to the Wi-Fi (trespassers, break-ins). Show registered household members in
**green**, everything else in **red**, and keep a report/log. Researched, not built.

### 7.1 Verdict: partly feasible, as a supplementary alarm signal only

| Want | Feasible? | Why |
|---|---|---|
| Notice that *some unknown device* is on the property, roughly where | **Yes, often** | Phones broadcast BLE advertisements (iPhones continuously, even locked) and Wi-Fi probe requests while not connected |
| Mark household members green | **Yes** | Known Wi-Fi MAC when connected, plus BLE Identity Resolving Keys (IRK) or the Home Assistant companion-app beacon when not |
| Count or track *individual* strangers over time | **Unreliable** | Unconnected phones randomize their addresses: BLE rotates about every 15 min, Wi-Fi probes change per scan. One phone can show up as many "devices". Research-grade linking exists (up to 97% in lab conditions) but is fragile in a real yard |
| A stranger's name or identity | **No** | Broadcasts carry no name, number or account. You get a random address, sometimes the maker (Apple, Samsung), and signal strength. Names exist only for people you register |
| Catch a careful intruder | **No** | Wi-Fi and Bluetooth off means invisible. (Note: iPhone 11+ and Pixel 8+ keep broadcasting Find My BLE for a while even when "off".) |
| Exact position | **Zone-level** | Several sensors needed; expect 5–15 m outdoors |

**Detection is probabilistic.** A locked phone sends Wi-Fi probes in bursts every few minutes to tens of minutes,
varying by model. Many idle Androids advertise BLE rarely. Someone walking quickly through may produce nothing.
This should **add to** cameras, motion and door sensors (SmartThings), not replace them.
Its best use: when the house is "armed / away / night" and a motion sensor fires, check for an unknown device nearby, then alert with a likely zone.

### 7.2 Why the current MikroTik setup can't do it
MikroTik APs don't report unconnected devices through any usable API (the sniffer and snooper take the radio out of service).
This needs **dedicated listening sensors**:

- **Recommended: Kismet** (open-source wireless monitoring). Raspberry Pi capture nodes, each with a
  monitor-mode USB Wi-Fi adapter (the Pi's built-in Wi-Fi can't do monitor mode) plus Bluetooth. They feed one Kismet server, which has a JSON
  API with per-device signal strength and alerts. The locator would poll Kismet the same way it polls RouterOS.
- **Cheaper: ESP32 nodes** running ESPresense or custom firmware. Good for BLE (10–30 m range), Wi-Fi 2.4 GHz only (ESP32-C5 for 5 GHz).
- Outdoors: weatherproof enclosures; PoE from the MikroTik switch where possible. Plan one node per zone.
  Rough range: BLE 10–50 m, Wi-Fi probes 30–100 m with a good antenna (estimate, verify in Phase 5a).

### 7.3 Green / red logic (design)
- **Green:** a registered device. Matched by connected Wi-Fi MAC (MikroTik), resolved BLE IRK, or companion-app iBeacon UUID.
- **Red:** an unresolved device that passes *all* of these filters:
  - signal above a threshold at a sensor inside the property polygon (drops road traffic and neighbours);
  - seen at least N times over M minutes (drops passers-by);
  - not on the **baseline** list (neighbours' fixed devices learned during a calibration week).
- **Amber:** unresolved but weak or brief. Shown, never alerted.
- **Clustering:** group unresolved addresses that appear together at the same sensors with similar signal into one "unknown presence",
  so one phone doesn't become ten red dots.
- **Known gap:** household phones also emit unresolved random Wi-Fi probes. Until each person's BLE IRK is set up they *will*
  create red/amber noise. That's why alerts should only fire in armed mode or when combined with motion.

### 7.4 Report / log
Event log (SQLite) with: first and last seen, zone(s), peak signal, which sensors heard it, maker if known, green/amber/red,
and a link to camera clips for that time window if cameras exist. Daily HTML/PDF report: timeline of red events plus a map of where they were heard.
Real-time push alerts via SmartThings or Home Assistant when armed. Map view: green, amber and red markers with zones.

### 7.5 Legal and privacy (check local law before deploying)
- US: passively receiving broadcast *metadata* (no message content) on your own property is generally considered lawful.
  There's no case law directly on point; the federal pen-register statute is the theoretical grey area. Never capture traffic contents.
- Point sensors at your own land; don't deliberately cover the road or neighbours' houses. Keep data only as long as needed (e.g. 30 days).
- EU/UK: MAC addresses are personal data under GDPR, and capturing beyond your own property likely falls outside the household exemption.
- Do **not** attempt to identify strangers. It's technically not possible from this data, and it would raise the legal risk.
- Cell-phone "IMSI catchers" are illegal for private use in the US. Out of scope.

### 7.6 Plan
- **5a – Field test before buying more (1 Pi + USB adapter running Kismet, about $100):** walk the property with test phones
  (iPhone, Android; locked and unlocked; Wi-Fi on, connected elsewhere, and off). Measure the detection rate per minute and the range per zone,
  and record neighbour/road noise over a week. **Go/no-go:** a locked phone must be detected within 2 minutes in at least 80% of trials in the key zones.
- **5b – Software:** a Kismet source in `locator/` (poll `/devices`), the green/amber/red classifier, clustering, baseline learning,
  property/zone polygons on the map, event log in SQLite, daily report.
- **5c – Household enrolment:** collect BLE IRKs (ESPresense/Bermuda method) or install the companion-app beacon on each person's phone.
- **5d – Integrate:** armed mode from SmartThings/HA; alert only on red + motion/door/camera event; links to clips.
- **5e – Deploy outdoor nodes** for the zones that passed 5a.
