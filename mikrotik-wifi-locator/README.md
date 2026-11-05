# MikroTik Wi-Fi Locator

Shows where the Wi-Fi devices (and so, roughly, the people) on your MikroTik
network are, on a live satellite map or your own floor plan, and in **Google Earth Pro**.

It reads the signal strength each access point reports for each client, turns it
into an estimated position, and serves:

| URL | What |
|---|---|
| `http://<host>:8080/` | Live web map (satellite / streets / your floor plan) |
| `http://<host>:8080/networklink.kml` | Open once in Google Earth Pro; it then updates itself every few seconds |
| `http://<host>:8080/api/state` | JSON, for Home Assistant / SmartThings / scripts |

No dependencies beyond Python 3.11+. Leaflet is bundled, so the map works on your LAN
without internet access. Only the satellite or street tiles need internet.

## How accurate is it?

You get **room or zone accuracy**, and it depends almost entirely on how many APs you have:

* RouterOS only reports a client on the AP it is **connected to**. So with standard
  MikroTik gear, each device shows up *near one AP*. The circle around it is the
  distance estimated from the signal strength. With 1 AP you get "home or not". With
  1 AP per room you get "which room".
* When a device roams between APs, the readings from both APs are combined for
  `window_seconds`, which gives in-between positions.
* For better accuracy, add **extra listeners** that `POST` to `/api/observations` (see below).
  Simulated, this gives about 2 m median error and the right room about 70% of the time.
  Building them is non-trivial: see [PLAN.md](PLAN.md) risks R1/R2 (5 GHz, BLE alternative).
  [PLAN.md](PLAN.md) also has the full feasibility study and test results.

## Setup

### 1. On the MikroTik

Edit the subnet and password in [`routeros-setup.rsc`](routeros-setup.rsc), then paste it into the
terminal. It creates a **read-only** user and enables the REST API (RouterOS 7) or the classic API (RouterOS 6).
If you use CAPsMAN, you only need to do this on the controller. Without CAPsMAN, do it on each AP.

### 2. On any always-on computer on the LAN (a Pi, NAS, or server)

```bash
cd mikrotik-wifi-locator
cp config.example.toml config.toml   # then edit it
python3 -m locator --once            # checks the router login and lists the radios clients are on
python3 -m locator                   # starts the map at http://<this-computer>:8080
```

`--once` prints every client along with the radio interface it is on, for example `cap-wifi1`.
Put those interface names into the matching `[[aps]]` entries in `config.toml`.
Any radio you haven't mapped yet also shows up as a yellow warning on the map.

### 3. Put the APs on the map

Start with `python3 -m locator --simulate` (fake people walking around, no router needed).
Zoom in on your house and **click where each AP physically is**. The popup gives the
`lat`/`lon` to paste into `config.toml`.

### 4. Calibrate (5 minutes, big improvement)

* Stand 1 m from an AP with your phone. Set `rssi_at_1m` to the signal shown in the sidebar.
* Walk to a spot about 10 m away. If the circle is too small, lower `path_loss_exponent`.
  If it is too big, raise it. Typical values are 2.5–3.5 indoors.
* You can override both settings per AP if one sits behind a thick wall.

### 5. Name people's devices

Add `[[devices]]` entries, or put a comment on the device's DHCP lease in RouterOS. That
comment is used as the name automatically. Phones use a **private Wi-Fi MAC per network**
by default. The MAC stays the same on your network, but it isn't the hardware MAC. You can
read it from the phone's Wi-Fi details screen or from the DHCP lease list.

Set `track = "known"` to show only the devices you've listed.

## Your own map / floor plan

Export a floor plan as a PNG. Then use the click-for-coordinates feature to find the
lat/lon of its south-west and north-east corners, and add:

```toml
[map.floorplan]
image = "floorplan.png"
bounds = [[south_lat, west_lon], [north_lat, east_lon]]
opacity = 0.7
```

It is drawn on the web map and sent to Google Earth as a ground overlay. Set `base = "blank"` to show only the plan.

## Google Earth

Use **Google Earth Pro** (desktop, free). Click **Open in Google Earth** in the sidebar,
or use *File → Open* on the downloaded `wifi-locator.kml`. Each device appears as a
coloured person icon with its accuracy circle, and the icons move as positions update.
The browser version of Google Earth can't load live feeds from a local server.

## Extra sensors (optional)

```http
POST /api/observations
X-Sensor-Token: <server.sensor_token>
{"sensor": "esp-hall", "readings": [{"mac": "12:34:56:78:9A:BC", "rssi": -61}]}
```

Add a matching `[[aps]]` entry with `sensor = "esp-hall"` and its lat/lon.

## Privacy

This shows where people are in real time. Use it on your own network, and make sure the people in your
household or workplace know it's running. In many places, covertly tracking other adults or
employees is illegal. Keep `server.username`/`password` set and don't expose port 8080 to the internet.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```
