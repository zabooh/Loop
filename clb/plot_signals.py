#!/usr/bin/env python3
"""
plot_signals.py - capture the CLB half-bridge HS/LS/PWM with the Saleae and plot
them with matplotlib (a wide view + a transition zoom showing the dead-time).

  python clb/plot_signals.py            # capture at dt=10 then plot -> PNGs
  python clb/plot_signals.py --dt 20
  python clb/plot_signals.py --no-capture  # re-plot the existing CSV only
"""
import argparse, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "clb_signals_csv", "digital.csv")
WIDE_PNG = os.path.join(HERE, "clb_signals.png")
ZOOM_PNG = os.path.join(HERE, "clb_deadtime_zoom.png")
DT_STEP_NS = 31.25   # BLE_clk = 32 MHz


def capture(dt, rate):
    import project_config
    from smoketest import Console, saleae_capture
    from saleae import automation
    c = Console(project_config.flasher_port(), echo=False)
    try:
        c.cmd(f"clb dt {dt}"); c.cmd("clb on")
        m = automation.Manager.connect(port=10430)
        try:
            dev = m.get_devices()[0].device_id
            saleae_capture(m, [0, 1, 2], rate, 0.0008,
                           os.path.join(HERE, "clb_signals_csv"), dev)
        finally:
            m.close()
    finally:
        c.close()


def read_steps(path):
    """Transition CSV -> dict of channel -> (times[], levels[]) step series."""
    ts, h, l, p = [], [], [], []
    with open(path, newline="") as f:
        r = csv.reader(f); next(r)
        for row in r:
            if len(row) < 4:
                continue
            try:
                ts.append(float(row[0])); h.append(int(float(row[1])))
                l.append(int(float(row[2]))); p.append(int(float(row[3])))
            except ValueError:
                continue
    return ts, h, l, p


def find_deadtime_window(ts, h, l):
    """Return (t_start, dt_ns) of the first both-low gap after t>5us."""
    for i in range(1, len(ts)):
        if ts[i] > 5e-6 and h[i] == 0 and l[i] == 0:
            j = i
            while j + 1 < len(ts) and h[j] == 0 and l[j] == 0:
                j += 1
            return ts[i], (ts[j] - ts[i]) * 1e9
    return ts[len(ts) // 2], 0.0


def plot(dt):
    ts, h, l, p = read_steps(CSV)
    t0 = ts[0]
    t = [(x - t0) * 1e6 for x in ts]   # microseconds

    # ---- wide view: a few periods of HS / LS / PWM ----
    fig, ax = plt.subplots(3, 1, figsize=(10, 5), sharex=True)
    for a, sig, name, col in ((ax[0], h, "HS (RC0)", "#1a7f37"),
                              (ax[1], l, "LS (RC1)", "#cf222e"),
                              (ax[2], p, "PWM (RC2, CLB counter)", "#0969da")):
        a.step(t, sig, where="post", color=col, linewidth=1.6)
        a.set_ylabel(name, rotation=0, ha="right", va="center", fontsize=9)
        a.set_yticks([0, 1]); a.set_ylim(-0.2, 1.2); a.grid(True, alpha=0.3)
    ax[0].set_xlim(0, 40)
    ax[2].set_xlabel("time [µs]")
    fig.suptitle(f"CLB half-bridge — HS/LS complementary from PWM, dead-time dt={dt} "
                 f"({dt*DT_STEP_NS:.0f} ns)", fontsize=11)
    fig.tight_layout()
    fig.savefig(WIDE_PNG, dpi=110)
    print(f"wrote {WIDE_PNG}")

    # ---- zoom: one transition, showing the both-low dead-time gap ----
    tg, dt_ns = find_deadtime_window(ts, h, l)
    c = (tg - t0) * 1e6
    fig2, ax2 = plt.subplots(figsize=(8, 3.2))
    ax2.step(t, [v + 2 for v in h], where="post", color="#1a7f37", linewidth=2, label="HS")
    ax2.step(t, l, where="post", color="#cf222e", linewidth=2, label="LS")
    ax2.axvspan(c, c + dt_ns / 1000.0, color="#9a6700", alpha=0.25)
    ax2.annotate(f"dead-time ≈ {dt_ns:.0f} ns\n(both low, no shoot-through)",
                 xy=(c + dt_ns / 2000.0, 1.5), ha="center", fontsize=9,
                 color="#6e5000")
    ax2.set_xlim(c - 0.6, c + 0.6)
    ax2.set_yticks([0.5, 2.5]); ax2.set_yticklabels(["LS", "HS"])
    ax2.set_ylim(-0.3, 3.3); ax2.set_xlabel("time [µs]"); ax2.grid(True, alpha=0.3)
    ax2.set_title(f"Dead-time at a switching edge (dt={dt} → {dt*DT_STEP_NS:.0f} ns nominal)")
    ax2.legend(loc="upper right", fontsize=8)
    fig2.tight_layout()
    fig2.savefig(ZOOM_PNG, dpi=110)
    print(f"wrote {ZOOM_PNG}  (measured gap {dt_ns:.0f} ns)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dt", type=int, default=10)
    ap.add_argument("--rate", type=int, default=100_000_000)
    ap.add_argument("--no-capture", action="store_true")
    args = ap.parse_args()
    if not args.no_capture:
        capture(args.dt, args.rate)
    plot(args.dt)


if __name__ == "__main__":
    main()
