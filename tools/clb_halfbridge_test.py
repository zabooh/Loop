#!/usr/bin/env python3
"""
clb_halfbridge_test.py
----------------------
Saleae hardware test for the CLB half-bridge (clb/clb_halfbridge.v) running on
RC0 (high-side) and RC1 (low-side) of the PIC16F13145.

It drives the console (`pulse freq`, `pulse a duty`, `clb dt`, `clb on`), captures
RC0+RC1 simultaneously, and checks the three properties that define a working
half-bridge with runtime dead-time:

  1. INPUT FOLLOWS PWM  - both sides switch at the PWM frequency. If they don't,
     the CLB input mux is not wired to PWM1 (wrong mux code) -> the whole design
     is dead. This is the check the hardware-in-the-loop driver keys its
     auto-search on.
  2. NON-OVERLAP (safety)- HS and LS are never high at the same time. A shoot-
     through here would destroy a real bridge, so the overlap time must be ~0.
  3. DEAD-TIME SCALES   - the both-low gap at each transition grows with `clb dt`
     (and is ~0 at dt=0). This proves the runtime-adjustable dead-time works.

Reused from smoketest.py: Console (serial), saleae_capture, raw-CSV parsing.

Standalone:
  python clb_halfbridge_test.py                 # full HW test + clb_halfbridge_report.html
  python clb_halfbridge_test.py --analyze DIR    # re-analyse a capture
  python clb_halfbridge_test.py --selftest       # analyser self-test (no hardware)
"""
import argparse
import csv
import os
import statistics
import sys

from testreport import Suite, Result, Check
import project_config
from smoketest import Console, saleae_capture, analyze_digital_csv

HS_CH = 0          # Saleae digital channel on RC0 (high-side)
LS_CH = 1          # Saleae digital channel on RC1 (low-side)

DEFAULT_FREQ = 62_500          # PWM is CLB-generated (cnt[8] = BLE_clk/512 ~= 62.5 kHz)
DEFAULT_RATE = 100_000_000     # 100 MS/s: resolve dead-times down to ~10 ns
FREQ_TOL = 0.10                # 10 % around the nominal CLB-generated frequency
DT_STEP_NS = 31.25             # one dt step = 1 TMR2 FOSC tick (32 MHz)
DT_TOL_NS = 40.0               # dead-time tolerance (~1 sample + edge skew)


# ============================ combined analysis ===========================
def _read_states(path):
    """Read a Saleae raw-data CSV into [(t, hs, ls), ...] at each transition."""
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        tcol, hcol, lcol = 0, None, None
        for i, h in enumerate(header):
            hl = h.strip().lower().replace(" ", "")
            if hl.startswith("time"):
                tcol = i
            if hl == f"channel{HS_CH}":
                hcol = i
            if hl == f"channel{LS_CH}":
                lcol = i
        if hcol is None or lcol is None:
            raise ValueError(f"channels not found in header {header}")
        states = []
        for row in reader:
            if not row or len(row) <= max(tcol, hcol, lcol):
                continue
            try:
                t = float(row[tcol]); hs = int(float(row[hcol])); ls = int(float(row[lcol]))
            except ValueError:
                continue
            states.append((t, hs, ls))
    return states


def analyze_halfbridge(path):
    """Measure overlap time, dead-time gaps and switching frequency from a
    two-channel (HS, LS) raw-data CSV."""
    states = _read_states(path)
    hs_meas = analyze_digital_csv(path, HS_CH)   # frequency/duty of the high-side
    if len(states) < 3:
        return dict(freq_hz=hs_meas["freq_hz"], cycles=hs_meas["cycles"],
                    total_s=0.0, overlap_s=0.0, overlap_frac=0.0,
                    deadtimes=[], deadtime_ns=0.0,
                    hs_level=hs_meas["level"], both_low_intervals=0)

    total = states[-1][0] - states[0][0]
    overlap = 0.0
    both_low = []
    period = 1.0 / hs_meas["freq_hz"] if hs_meas["freq_hz"] > 0 else total
    for (t0, h0, l0), (t1, _, _) in zip(states, states[1:]):
        dur = t1 - t0
        if h0 and l0:
            overlap += dur                       # shoot-through interval
        elif not h0 and not l0:
            # both low = dead-time gap; keep only the short ones (transition gaps,
            # not a long idle), i.e. shorter than a quarter PWM period
            if dur < period * 0.25:
                both_low.append(dur)
    deadtime = statistics.median(both_low) if both_low else 0.0
    return dict(freq_hz=hs_meas["freq_hz"], cycles=hs_meas["cycles"],
                total_s=total, overlap_s=overlap,
                overlap_frac=(overlap / total if total > 0 else 0.0),
                deadtimes=both_low, deadtime_ns=deadtime * 1e9,
                hs_level=hs_meas["level"], both_low_intervals=len(both_low))


# ============================ hardware run ===========================
def setup_input(console, freq):
    """No-op: the PWM input is generated inside the CLB (free-running counter),
    not by the PWM module, so there is nothing to set up here."""
    return


def capture_dt(console, manager, device_id, sample_rate, base_outdir, freq, dt):
    """Set the dead-time, enable the CLB, capture RC0+RC1, return measurements."""
    console.cmd(f"clb dt {dt}")
    console.cmd("clb on")
    duration = max(0.01, 60.0 / freq)
    outdir = os.path.join(base_outdir, f"dt{dt}")
    csv_path = saleae_capture(manager, [HS_CH, LS_CH], sample_rate, duration,
                              outdir, device_id)
    console.cmd("clb off")
    m = analyze_halfbridge(csv_path)
    print(f"      dt={dt}: HS freq {m['freq_hz']:.0f} Hz, overlap {m['overlap_frac']*100:.3f}%, "
          f"dead-time {m['deadtime_ns']:.0f} ns ({m['both_low_intervals']} gaps)")
    return m


def probe_input(console, manager, device_id, sample_rate, base_outdir, freq):
    """Quick check used by the HIL mux search: does HS switch at the PWM freq?
    Returns (ok, measured_freq_hz)."""
    setup_input(console, freq)
    m = capture_dt(console, manager, device_id, sample_rate, base_outdir, freq, 3)
    ok = m["freq_hz"] > 0 and abs(m["freq_hz"] - freq) <= freq * FREQ_TOL
    return ok, m["freq_hz"]


def run_suite(console, manager, device_id, sample_rate, base_outdir,
              freq=DEFAULT_FREQ, dts=(2, 5, 10, 20)) -> Suite:
    """Timer+CLC half-bridge suite: per dt check switching, non-overlap, and that the
    measured dead-time matches dt x 31.25 ns; then check the dead-time scales with dt."""
    os.makedirs(base_outdir, exist_ok=True)
    suite = Suite("CLB half-bridge (Saleae)",
                  f"RC0=HS, RC1=LS; CLB-generated PWM ~{freq} Hz; TMR2+CLC dead-time, "
                  f"dt swept over {list(dts)} (dead-time = dt x {DT_STEP_NS:.2f} ns).")

    meas = {dt: capture_dt(console, manager, device_id, sample_rate, base_outdir, freq, dt)
            for dt in dts}

    # per dt: switching present, non-overlap, dead-time matches dt x 31.25 ns
    for dt in dts:
        m = meas[dt]
        exp_ns = dt * DT_STEP_NS
        checks, rows = [], []
        ok_freq = m["freq_hz"] > 0 and abs(m["freq_hz"] - freq) <= freq * FREQ_TOL
        checks.append(Check("HS/LS switch at the CLB PWM rate", ok_freq,
                            f"measured {m['freq_hz']:.0f} Hz (nominal {freq} Hz)"))
        rows.append(["switching freq", f"{m['freq_hz']:.0f} Hz", f"{freq} Hz",
                     f"{FREQ_TOL*100:.0f}%", "PASS" if ok_freq else "FAIL"])
        ok_ov = m["overlap_frac"] <= 0.001      # both-high must be essentially zero
        checks.append(Check("non-overlap (no shoot-through)", ok_ov,
                            f"HS&LS both-high {m['overlap_frac']*100:.4f}% of the time"))
        rows.append(["overlap (HS&LS high)", f"{m['overlap_frac']*100:.4f}%", "0%",
                     "0.1%", "PASS" if ok_ov else "FAIL"])
        ok_dt = abs(m["deadtime_ns"] - exp_ns) <= DT_TOL_NS
        checks.append(Check("dead-time matches dt x 31.25 ns", ok_dt,
                            f"measured {m['deadtime_ns']:.0f} ns, expected {exp_ns:.0f} ns"))
        rows.append(["dead-time", f"{m['deadtime_ns']:.0f} ns", f"{exp_ns:.0f} ns",
                     f"{DT_TOL_NS:.0f} ns", "PASS" if ok_dt else "FAIL"])
        suite.add(Result(f"dt={dt}  ({exp_ns:.0f} ns)", all(c.passed for c in checks),
                         f"HS {m['freq_hz']:.0f} Hz, dead-time {m['deadtime_ns']:.0f} ns, "
                         f"overlap {m['overlap_frac']*100:.3f}%",
                         checks, ["Check", "measured", "expected", "tol", "result"], rows))

    # dead-time scales linearly + monotonically with dt
    dt_list = sorted(meas)
    ns = [meas[dt]["deadtime_ns"] for dt in dt_list]
    checks, rows = [], []
    mono = all(ns[i + 1] > ns[i] for i in range(len(ns) - 1))
    checks.append(Check("dead-time increases monotonically with dt", mono,
                        " < ".join(f"{v:.0f}ns(dt{d})" for d, v in zip(dt_list, ns))))
    for d, v in zip(dt_list, ns):
        rows.append([f"dt={d}", f"{v:.0f} ns", f"{d*DT_STEP_NS:.0f} ns",
                     f"{DT_TOL_NS:.0f} ns", "PASS" if abs(v - d*DT_STEP_NS) <= DT_TOL_NS else "FAIL"])
    step = (ns[-1] - ns[0]) / (dt_list[-1] - dt_list[0]) if dt_list[-1] != dt_list[0] else 0.0
    suite.add(Result("dead-time vs dt (linearity)", all(c.passed for c in checks),
                     f"~{step:.1f} ns per dt step (nominal {DT_STEP_NS:.2f} ns)",
                     checks, ["setting", "measured", "expected", "tol", "result"], rows))
    return suite


def run_hardware(args):
    from saleae import automation
    print(f"Opening serial console on {args.port} ...")
    console = Console(args.port, echo=not args.quiet_cli)
    print("Connecting to Logic 2 automation ...")
    manager = automation.Manager.connect(port=args.automation_port)
    device_id = args.device_id
    if device_id is None:
        devs = manager.get_devices()
        if not devs:
            print("ERROR: no Saleae device found."); return 1
        device_id = devs[0].device_id
    try:
        suite = run_suite(console, manager, device_id, args.sample_rate, args.csv_dir,
                          freq=args.freq)
    finally:
        try:
            console.cmd("clb off")
        finally:
            console.close()
            manager.close()

    from testreport import write_html
    ok = write_html("clb_halfbridge_report.html", "CLB Half-Bridge Test",
                    {"device": "PIC16F13145", "PWM input": f"{args.freq} Hz"}, [suite])
    npass = sum(1 for r in suite.results if r.passed)
    print(f"\n========  {npass}/{len(suite.results)} cases passed  ========")
    return 0 if ok else 1


# ============================ offline modes ===========================
def run_analyze(path):
    if os.path.isdir(path):
        path = os.path.join(path, "digital.csv")
    m = analyze_halfbridge(path)
    print(f"{path}:\n  HS freq {m['freq_hz']:.1f} Hz, overlap {m['overlap_frac']*100:.4f}%, "
          f"dead-time {m['deadtime_ns']:.1f} ns over {m['both_low_intervals']} gaps")
    return 0


def _write_synth_hb_csv(path, freq, dt_ns, cycles=40):
    """Synthetic complementary half-bridge with dead-time, for the analyser self-test."""
    period = 1.0 / freq
    dt = dt_ns * 1e-9
    rows = [(0.0, 0, 0)]
    for k in range(cycles):
        t = k * period
        # pwm high half: HS high after dead-time, LS low
        rows.append((t, 0, 0))                       # both low (dead-time start)
        rows.append((t + dt, 1, 0))                  # HS on
        # pwm low half
        rows.append((t + period / 2, 0, 0))          # both low (dead-time start)
        rows.append((t + period / 2 + dt, 0, 1))     # LS on
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time [s]", "Channel 0", "Channel 1"])
        for t, h, l in rows:
            w.writerow([f"{t:.9f}", h, l])


def run_selftest():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="hb_")
    ok = True
    for freq, dt_ns in ((10000, 0.0), (10000, 100.0), (10000, 220.0)):
        path = os.path.join(tmp, "digital.csv")
        _write_synth_hb_csv(path, freq, dt_ns)
        m = analyze_halfbridge(path)
        print(f"synthetic freq={freq} dt={dt_ns}ns -> HS {m['freq_hz']:.0f} Hz, "
              f"overlap {m['overlap_frac']*100:.4f}%, dead-time {m['deadtime_ns']:.0f} ns")
        if m["overlap_frac"] > 1e-6:
            print("  FAIL overlap should be 0"); ok = False
        if abs(m["deadtime_ns"] - dt_ns) > 25 and dt_ns > 0:
            print(f"  FAIL dead-time {m['deadtime_ns']:.0f} vs {dt_ns}"); ok = False
        if abs(m["freq_hz"] - freq) > freq * 0.02:
            print(f"  FAIL freq {m['freq_hz']}"); ok = False
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Saleae CLB half-bridge test")
    ap.add_argument("--port", default=project_config.flasher_port())
    ap.add_argument("--sample-rate", type=int, default=DEFAULT_RATE)
    ap.add_argument("--freq", type=int, default=DEFAULT_FREQ, help="PWM input frequency (Hz)")
    ap.add_argument("--csv-dir", default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "clb_hb_csv"))
    ap.add_argument("--device-id", default=None)
    ap.add_argument("--automation-port", type=int, default=10430)
    ap.add_argument("--quiet-cli", action="store_true")
    ap.add_argument("--analyze", metavar="CSV_OR_DIR")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return run_selftest()
    if args.analyze:
        return run_analyze(args.analyze)
    return run_hardware(args)


if __name__ == "__main__":
    sys.exit(main())
