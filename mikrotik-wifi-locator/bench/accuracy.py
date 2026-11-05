"""Accuracy study. House 18 x 12 m, 3x2 rooms of 6x6 m, walls cost 4 dB each.
Truth: n=3.3, P0=-42 dBm, 4 dB slow shadowing + 2 dB fast noise.
Config (deliberately imperfect calibration): n=3.0, P0=-40."""
import sys, math, random, statistics as st
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from locator.config import Config, AccessPoint
from locator.positioning import Locator, LocalGrid
from locator.routeros import Observation
W, H, RW = 18.0, 12.0, 6.0
LAT0, LON0 = 39.7392, -104.9902
room = lambda x, y: (min(int(x // RW), 2), min(int(y // RW), 1))
def layout(n):
    return {1: [(9, 6)], 2: [(4.5, 6), (13.5, 6)], 3: [(3, 3), (9, 9), (15, 3)],
            4: [(3, 3), (15, 3), (3, 9), (15, 9)], 6: [(3 + 6*i, 3 + 6*j) for i in range(3) for j in range(2)]}[n]
def run(n_aps, mode, seed=1, steps=1500, true_n=3.3, true_p0=-42.0, wall_db=4.0):
    rnd = random.Random(seed)
    g0 = LocalGrid([AccessPoint("o", LAT0, LON0)])
    aps = []
    for i, (x, y) in enumerate(layout(n_aps)):
        lat, lon = g0.to_latlon(x - W/2, y - H/2)
        aps.append(AccessPoint(f"ap{i}", lat, lon, router="r", interfaces=[f"w{i}"]))
    cfg = Config(path=None, routers=[], aps=aps, devices={}, rssi_at_1m=-40, path_loss_exponent=3.0, window_seconds=20, smoothing=0.4)
    loc = Locator(cfg); grid = loc.grid
    apxy = [(x, y) for x, y in layout(n_aps)]
    shadow = {}
    p = [rnd.uniform(0, W), rnd.uniform(0, H)]; goal = [rnd.uniform(0, W), rnd.uniform(0, H)]
    assoc = None; errs = []; room_ok = 0; t = 1e6
    for k in range(steps):
        t += 3
        # walk 1 m/s with pauses (people mostly sit still)
        if rnd.random() < 0.7:
            dx, dy = goal[0]-p[0], goal[1]-p[1]; d = math.hypot(dx, dy)
            if d < 3: goal = [rnd.uniform(0, W), rnd.uniform(0, H)]
            else: p = [p[0] + dx/d*3, p[1] + dy/d*3]
        cell = (int(p[0]), int(p[1]))
        sig = []
        for i, (ax, ay) in enumerate(apxy):
            key = (i, cell)
            if key not in shadow: shadow[key] = rnd.gauss(0, 4)
            d = max(0.5, math.hypot(p[0]-ax, p[1]-ay))
            walls = sum(abs(a - b) for a, b in zip(room(*p), room(ax, ay)))
            sig.append(true_p0 - 10*true_n*math.log10(d) - wall_db*walls + shadow[key] + rnd.gauss(0, 2))
        best = max(range(len(sig)), key=lambda i: sig[i])
        if assoc is None or sig[best] > sig[assoc] + 6: assoc = best
        heard = [assoc] if mode == "assoc" else [i for i in range(len(sig)) if sig[i] > -88]
        loc.ingest([Observation("r", f"w{i}", "AA:00:00:00:00:01", round(sig[i]), t) for i in heard])
        tr = loc.tracks["AA:00:00:00:00:01"]
        ex, ey = tr.x + W/2, tr.y + H/2
        if k > 20:
            errs.append(math.hypot(ex - p[0], ey - p[1]))
            room_ok += room(min(max(ex, 0), W-0.01), min(max(ey, 0), H-0.01)) == room(*p)
    n = len(errs); errs.sort()
    return st.median(errs), errs[int(n*0.9)], 100*room_ok/n
if __name__ == "__main__":
    print(f"{'APs':>3} {'mode':<28} {'median err':>10} {'90% err':>8} {'right room':>10}")
    for n_aps in (1, 2, 3, 4, 6):
        for mode, label in (("assoc", "stock MikroTik (assoc only)"), ("all", "+ sniffer sensors (all hear)")):
            r = [run(n_aps, mode, seed=s) for s in range(8)]
            med = st.mean(x[0] for x in r); p90 = st.mean(x[1] for x in r); rm = st.mean(x[2] for x in r)
            print(f"{n_aps:>3} {label:<28} {med:>8.1f} m {p90:>6.1f} m {rm:>9.0f}%")
    print("(room guess baseline by chance = 17%; house has 6 rooms)")
