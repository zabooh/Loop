#!/usr/bin/env python3
"""
freq_sweep.py
-------------
Sweep PWM frequencies and verify each one **with the Saleae logic analyzer**:
for every requested frequency the tool sets it on the PIC, records RC0, measures
the real frequency from the captured data and plots how far it deviates from the
requested input (the deviation is the quantisation of the integer Timer2 divider:
the frequency can only be 8 MHz / (N * prescale), N in 2..256, prescale 1..128).

Each point needs a capture, so the number of points is modest and the usable top
frequency is bounded by the analyzer sample rate (default 10 MS/s -> up to about
100 kHz with good resolution). Raise --sample-rate and --fmax for higher ranges.

Output: a summary CSV (requested / firmware-reported / measured / deviation) and
a matplotlib figure (requested-vs-measured and deviation in %).

Requirements: Logic 2 with the automation server enabled, Saleae channel 0 on
RC0; `pip install logic2-automation pyserial matplotlib numpy`.

Usage:
  python freq_sweep.py                                  # sweep on COM12, show plot
  python freq_sweep.py --points 60 --fmax 100000
  python freq_sweep.py --sample-rate 25000000 --fmax 250000
  python freq_sweep.py --no-show                        # save PNG/CSV only
"""
import argparse
import csv
import os
import re
import sys
import time

import numpy as np

# reuse the proven serial console and CSV analyser from the smoke test
from smoketest import Console, analyze_digital_csv
import project_config

RC0_CH = 0                       # Saleae digital channel wired to RC0 (PWM1)


def capture_freq(manager, device_id, channel, sample_rate, duration, outdir):
    """Record one channel for `duration` s and export it to <outdir>/digital.csv."""
    from saleae import automation
    dev = automation.LogicDeviceConfiguration(
        enabled_digital_channels=[channel], digital_sample_rate=sample_rate)
    cfg = automation.CaptureConfiguration(
        capture_mode=automation.TimedCaptureMode(duration_seconds=duration))
    os.makedirs(outdir, exist_ok=True)
    cap = manager.start_capture(device_id=device_id, device_configuration=dev,
                                capture_configuration=cfg)
    try:
        cap.wait()
        cap.export_raw_data_csv(directory=outdir, digital_channels=[channel])
    finally:
        cap.close()
    return os.path.join(outdir, "digital.csv")


def build_points(fmin, fmax, points):
    xs = np.logspace(np.log10(fmin), np.log10(fmax), points)
    return sorted(set(int(round(x)) for x in xs))


def run_sweep(args):
    from saleae import automation

    reqs = build_points(args.fmin, args.fmax, args.points)
    print(f"Sweeping {len(reqs)} frequencies {args.fmin}..{args.fmax} Hz, "
          f"Saleae @ {args.sample_rate/1e6:.1f} MS/s on {args.port}")

    # open the serial port first so a busy COM fails fast (before the Saleae)
    console = Console(args.port, echo=False)
    console.cmd("pulse a duty 50")          # 50 % so edges are easy to detect
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

    capdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "freq_sweep_cap")
    rows = []   # (req, firmware, measured, dev_pct, samples_per_period)
    try:
        for i, req in enumerate(reqs):
            resp = console.cmd(f"pulse freq {req}")
            m = re.search(r"Frequency\s*->\s*([\d.]+)\s*Hz", resp)
            fw = float(m.group(1)) if m else float("nan")

            spp = args.sample_rate / req                 # samples per period
            duration = max(0.02, 60.0 / req)
            csv_path = capture_freq(manager, device_id, RC0_CH,
                                    args.sample_rate, duration, capdir)
            meas = analyze_digital_csv(csv_path, RC0_CH)["freq_hz"]
            dev = (meas - req) / req * 100.0 if meas else float("nan")
            rows.append((req, fw, meas, dev, spp))

            warn = "  (coarse: <50 samples/period!)" if spp < 50 else ""
            print(f"  {i+1:3d}/{len(reqs)}  req {req:>8d} Hz  fw {fw:>10.2f}  "
                  f"meas {meas:>10.2f}  dev {dev:+.3f} %{warn}")
    finally:
        console.close()
        manager.close()

    # --- summary CSV ---
    with open(args.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["requested_hz", "firmware_hz", "measured_hz",
                    "deviation_pct", "samples_per_period"])
        w.writerows(rows)
    print(f"\nWrote {len(rows)} points to {args.csv}")

    good = [r for r in rows if not np.isnan(r[3])]
    if good:
        worst = max(good, key=lambda r: abs(r[3]))
        print(f"Max |deviation| = {abs(worst[3]):.3f} % at {worst[0]} Hz "
              f"(measured {worst[2]:.2f} Hz)")
        print(f"Median |deviation| = "
              f"{float(np.median([abs(r[3]) for r in good])):.4f} %")

    plot(rows, args)
    return 0


def plot(rows, args):
    import matplotlib
    if args.no_show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    req = np.array([r[0] for r in rows], dtype=float)
    fw = np.array([r[1] for r in rows], dtype=float)
    meas = np.array([r[2] for r in rows], dtype=float)
    dev = np.array([r[3] for r in rows], dtype=float)
    dev_fw = (fw - req) / req * 100.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9), constrained_layout=True)
    fig.suptitle(f"PIC16F13145 PWM frequency sweep, Saleae-verified "
                 f"({len(rows)} points)")

    # 1) requested vs measured
    lim = [min(req.min(), meas.min()), max(req.max(), meas.max())]
    ax1.plot(lim, lim, "k--", lw=1, label="ideal (measured = requested)")
    ax1.plot(req, meas, ".", ms=5, color="tab:blue", label="Saleae measured")
    ax1.set_xscale("log"); ax1.set_yscale("log")
    ax1.set_xlabel("requested frequency [Hz]")
    ax1.set_ylabel("measured frequency [Hz]")
    ax1.set_title("Requested vs. measured frequency")
    ax1.grid(True, which="both", ls=":", alpha=0.5)
    ax1.legend()

    # 2) deviation: measured (Saleae) and firmware-reported
    ax2.axhline(0, color="k", lw=1)
    ax2.plot(req, dev_fw, "x", ms=5, color="tab:green",
             label="firmware-reported deviation")
    ax2.plot(req, dev, ".", ms=6, color="tab:red", label="Saleae-measured deviation")
    ax2.set_xscale("log")
    ax2.set_xlabel("requested frequency [Hz]")
    ax2.set_ylabel("deviation from requested [%]")
    ax2.set_title("Deviation of generated frequency from the requested input")
    ax2.grid(True, which="both", ls=":", alpha=0.5)
    ax2.legend()

    fig.savefig(args.out, dpi=130)
    print(f"Saved plot to {args.out}")
    if not args.no_show:
        plt.show()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Saleae-verified PWM frequency sweep")
    ap.add_argument("--port", default=project_config.flasher_port(),
                    help="serial port of the PIC console")
    ap.add_argument("--fmin", type=int, default=244, help="lowest requested Hz")
    ap.add_argument("--fmax", type=int, default=100_000, help="highest requested Hz")
    ap.add_argument("--points", type=int, default=50, help="number of sweep points (log-spaced)")
    ap.add_argument("--sample-rate", type=int, default=10_000_000,
                    help="Saleae digital sample rate in S/s (default 10 MS/s)")
    ap.add_argument("--device-id", default=None, help="Saleae device id (default: first found)")
    ap.add_argument("--automation-port", type=int, default=10430)
    ap.add_argument("--csv", default=os.path.join(here, "freq_sweep.csv"))
    ap.add_argument("--out", default=os.path.join(here, "freq_sweep.png"))
    ap.add_argument("--no-show", action="store_true", help="save files, do not open a window")
    args = ap.parse_args()
    return run_sweep(args)


if __name__ == "__main__":
    sys.exit(main())
