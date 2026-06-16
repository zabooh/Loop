#!/usr/bin/env python3
"""
duty_sweep.py
-------------
Sweep the PWM duty cycle at several frequencies and verify **each point with the
Saleae**, then plot how far the generated duty deviates from the requested input.

The duty cycle is quantised to the 10-bit value DC = duty% * 4 * N / 100, where
N = T2PR+1 depends on the frequency. So the achievable duty resolution gets
coarser as the frequency rises (fewer steps per period) — this test makes that
visible by sweeping the duty at a few frequencies and overlaying the results.

For every (frequency, requested duty) it sends `pulse a duty`, records RC0,
measures the real duty cycle from the capture and stores it.

Requirements: Logic 2 with the automation server enabled, Saleae channel 0 on
RC0; `pip install logic2-automation pyserial matplotlib numpy`.

Usage:
  python duty_sweep.py                                   # default freqs, show plot
  python duty_sweep.py --freqs 1000,10000,50000
  python duty_sweep.py --duty-step 2                     # finer duty sweep
  python duty_sweep.py --sample-rate 25000000
  python duty_sweep.py --no-show                         # save PNG/CSV only
"""
import argparse
import csv
import os
import re
import sys

import numpy as np

from smoketest import Console, analyze_digital_csv
from freq_sweep import capture_freq
import project_config

RC0_CH = 0                       # Saleae digital channel wired to RC0 (PWM1)

# Valid Logic 8 digital sample rates (probed: 100 MS/s is the max it accepts).
VALID_RATES = (10_000_000, 25_000_000, 50_000_000, 100_000_000)
TARGET_SPP = 2000                # aim for >=2000 samples/period (~0.05 pp duty)


def choose_sample_rate(freq, target_spp=TARGET_SPP):
    """Smallest valid rate giving >= target_spp samples/period (capped at max).
    The Saleae duty resolution is one sample per period (= freq / sample_rate),
    so this guarantees a fine enough time resolution per frequency."""
    for r in VALID_RATES:
        if r / freq >= target_spp:
            return r
    return VALID_RATES[-1]


def duty_points(step):
    """Requested duty values 0..100 plus a few near the ends."""
    pts = set(range(0, 101, step))
    pts.update([1, 2, 98, 99])
    return sorted(p for p in pts if 0 <= p <= 100)


def run_sweep(args):
    from saleae import automation

    freqs = [int(x) for x in args.freqs.split(",") if x.strip()]
    duties = duty_points(args.duty_step)
    rate_str = "auto (per frequency)" if not args.sample_rate \
        else f"{args.sample_rate/1e6:.1f} MS/s"
    print(f"Duty sweep at {freqs} Hz, {len(duties)} duty points each, "
          f"Saleae @ {rate_str} on {args.port}")

    console = Console(args.port, echo=False)        # open serial first (fail fast)
    console.cmd("pulse a on")

    print("Connecting to Logic 2 automation ...")
    manager = automation.Manager.connect(port=args.automation_port)
    device_id = args.device_id
    if device_id is None:
        devs = manager.get_devices()
        if not devs:
            print("ERROR: no Saleae device found in Logic 2.")
            console.close()
            return 1
        device_id = devs[0].device_id
        print(f"  using device {device_id} ({devs[0].device_type})")

    capdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "duty_sweep_cap")
    rows = []   # (freq, req_duty, fw_duty, meas_duty, dev)
    try:
        for f in freqs:
            console.cmd(f"pulse freq {f}")
            duration = max(0.02, 60.0 / f)
            sr = args.sample_rate or choose_sample_rate(f)   # 0 => auto per freq
            spp = sr / f
            print(f"\n  f = {f} Hz  @ {sr/1e6:.0f} MS/s ({spp:.0f} samples/period,"
                  f" ~{100.0/spp:.3f} pp duty resolution)"
                  f"{'  COARSE' if spp < 100 else ''}")
            for d in duties:
                resp = console.cmd(f"pulse a duty {d}")
                m = re.search(r"Duty A\s*->\s*([\d.]+)\s*%", resp)
                fw = float(m.group(1)) if m else float("nan")

                csv_path = capture_freq(manager, device_id, RC0_CH,
                                        sr, duration, capdir)
                meas = analyze_digital_csv(csv_path, RC0_CH)["duty_pct"]
                dev = meas - d
                rows.append((f, d, fw, meas, dev))
                print(f"    duty req {d:6.1f} %  fw {fw:6.2f} %  "
                      f"meas {meas:6.2f} %  dev {dev:+.2f} pp")
    finally:
        console.close()
        manager.close()

    # --- summary CSV ---
    with open(args.csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz", "requested_duty_pct", "firmware_duty_pct",
                    "measured_duty_pct", "deviation_pp"])
        w.writerows(rows)
    print(f"\nWrote {len(rows)} points to {args.csv}")

    worst = max(rows, key=lambda r: abs(r[4]))
    print(f"Max |deviation| = {abs(worst[4]):.2f} pp at {worst[0]} Hz, "
          f"{worst[1]} % requested")

    plot(rows, freqs, args)
    return 0


def plot(rows, freqs, args):
    import matplotlib
    if args.no_show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9), constrained_layout=True)
    fig.suptitle(f"PIC16F13145 PWM duty-cycle sweep, Saleae-verified "
                 f"({len(rows)} points)")
    colors = plt.cm.viridis(np.linspace(0, 0.85, len(freqs)))

    ax1.plot([0, 100], [0, 100], "k--", lw=1, label="ideal (measured = requested)")
    ax2.axhline(0, color="k", lw=1)
    for f, c in zip(freqs, colors):
        sub = [r for r in rows if r[0] == f]
        req = np.array([r[1] for r in sub], dtype=float)
        fw = np.array([r[2] for r in sub], dtype=float)
        meas = np.array([r[3] for r in sub], dtype=float)
        dev = np.array([r[4] for r in sub], dtype=float)
        label = f"{f/1000:g} kHz" if f >= 1000 else f"{f} Hz"
        ax1.plot(req, meas, ".-", ms=5, lw=0.8, color=c, label=label)
        ax2.plot(req, dev, ".-", ms=5, lw=0.8, color=c, label=label)
        ax2.plot(req, fw - req, "x", ms=5, color=c, alpha=0.6)   # firmware quantisation

    ax1.set_xlabel("requested duty cycle [%]")
    ax1.set_ylabel("measured duty cycle [%]")
    ax1.set_title("Requested vs. measured duty cycle")
    ax1.grid(True, ls=":", alpha=0.5); ax1.legend()

    ax2.set_xlabel("requested duty cycle [%]")
    ax2.set_ylabel("deviation [percentage points]")
    ax2.set_title("Deviation from requested duty  "
                  "(dots = Saleae-measured, x = firmware-reported / quantisation)")
    ax2.grid(True, ls=":", alpha=0.5); ax2.legend()

    fig.savefig(args.out, dpi=130)
    print(f"Saved plot to {args.out}")
    if not args.no_show:
        plt.show()


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Saleae-verified PWM duty-cycle sweep")
    ap.add_argument("--port", default=project_config.flasher_port(),
                    help="serial port of the PIC console")
    ap.add_argument("--freqs", default="1000,10000,50000",
                    help="comma-separated frequencies in Hz")
    ap.add_argument("--duty-step", type=int, default=5, help="duty sweep step in %%")
    ap.add_argument("--sample-rate", type=int, default=0,
                    help="Saleae digital sample rate in S/s; 0 = auto per frequency "
                         "(>=2000 samples/period, capped at 100 MS/s)")
    ap.add_argument("--device-id", default=None, help="Saleae device id (default: first found)")
    ap.add_argument("--automation-port", type=int, default=10430)
    ap.add_argument("--csv", default=os.path.join(here, "duty_sweep.csv"))
    ap.add_argument("--out", default=os.path.join(here, "duty_sweep.png"))
    ap.add_argument("--no-show", action="store_true", help="save files, do not open a window")
    args = ap.parse_args()
    return run_sweep(args)


if __name__ == "__main__":
    sys.exit(main())
