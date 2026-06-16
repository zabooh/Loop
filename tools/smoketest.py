#!/usr/bin/env python3
"""
smoketest.py
------------
Hardware-in-the-loop smoke test for the Loop firmware (PIC16F13145).

For each test case it
  1. sends `pulse ...` commands to the PIC over the serial console (COM12),
  2. records RC0 (digital ch0) and RC1 (digital ch1) with a Saleae Logic
     analyzer via the Logic 2 automation API and exports the raw data to
     `digital.csv`,
  3. analyses that CSV to measure the real frequency and duty cycle on each
     channel, and
  4. compares the measurement against the value the firmware reports it
     generated (`pulse status`).

Requirements:
  * Logic 2 running with the automation server enabled
    (Preferences > Automation, default port 10430).
  * Saleae channel 0 wired to RC0, channel 1 wired to RC1, common ground.
  * `pip install logic2-automation pyserial`

Usage:
  python smoketest.py                       # full HW test on COM12
  python smoketest.py --port COM12 --sample-rate 10000000
  python smoketest.py --analyze <dir>       # only re-analyse a digital.csv
  python smoketest.py --selftest            # validate the analyser, no hardware

Notes on tolerances: the PIC runs from the internal HFINTOSC (±2 % at
calibration), so the absolute frequency may deviate a few percent from nominal.
The duty cycle is a ratio and is checked tighter.
"""
import argparse
import csv
import os
import re
import statistics
import sys
import time

from testreport import Suite, Result, Check, write_html
import project_config

RC0_CH = 0          # Saleae digital channel on RC0 (signal A / PWM1)
RC1_CH = 1          # Saleae digital channel on RC1 (signal B / PWM2)

FREQ_TOL = 0.03     # 3 %  (covers HFINTOSC tolerance + measurement)
DUTY_TOL = 2.0      # 2 percentage points


# ============================ CSV analysis ===========================
def _analyze_edges(edges):
    """edges: list of (time, level) at each transition of one channel."""
    if len(edges) < 2:
        level = edges[0][1] if edges else 0
        return dict(freq_hz=0.0, duty_pct=(100.0 if level else 0.0),
                    cycles=0, level=level)

    rises = [t for (t, v) in edges if v == 1]
    falls = [t for (t, v) in edges if v == 0]

    periods, duties = [], []
    for i in range(len(rises) - 1):
        p = rises[i + 1] - rises[i]
        nf = next((tf for tf in falls if rises[i] < tf < rises[i + 1]), None)
        if nf is not None and p > 0:
            periods.append(p)
            duties.append((nf - rises[i]) / p * 100.0)

    if not periods:
        return dict(freq_hz=0.0, duty_pct=0.0, cycles=0, level=edges[-1][1])

    period = statistics.median(periods)
    return dict(freq_hz=1.0 / period,
                duty_pct=statistics.median(duties),
                cycles=len(periods),
                level=edges[-1][1])


def analyze_digital_csv(path, channel):
    """Measure frequency and duty cycle of one digital channel from a
    Saleae raw-data CSV (transition rows: Time [s], Channel 0, Channel 1...)."""
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        tcol, ccol = 0, None
        for i, h in enumerate(header):
            hl = h.strip().lower()
            if hl.startswith("time"):
                tcol = i
            if hl.replace(" ", "") == f"channel{channel}":
                ccol = i
        if ccol is None:
            raise ValueError(f"channel {channel} not found in header {header}")

        edges, prev = [], None
        for row in reader:
            if not row or len(row) <= max(tcol, ccol):
                continue
            try:
                t = float(row[tcol])
                v = int(float(row[ccol]))
            except ValueError:
                continue
            if prev is None or v != prev:
                edges.append((t, v))
                prev = v
    return _analyze_edges(edges)


# ============================ Serial console =========================
class Console:
    def __init__(self, port, baud=115200, timeout=1.0, echo=True):
        import serial
        self.s = serial.Serial(port, baud, timeout=timeout)
        self.s.dtr = True            # CDC data path needs DTR/RTS asserted
        self.s.rts = True
        self.echo = echo             # print every CLI line sent/received
        time.sleep(0.3)
        self.s.reset_input_buffer()

    def cmd(self, line, wait=0.4):
        self.s.reset_input_buffer()
        self.s.write((line + "\r").encode())
        time.sleep(wait)
        data = self.s.read(self.s.in_waiting or 1)
        time.sleep(0.05)
        if self.s.in_waiting:
            data += self.s.read(self.s.in_waiting)
        resp = data.decode("ascii", "ignore")
        if self.echo:
            print(f"      CLI << {line}")
            for ln in resp.splitlines():
                ln = ln.strip()
                if ln and ln != line and ln != ">":   # skip echo + bare prompt
                    print(f"      CLI >> {ln}")
        return resp

    def close(self):
        self.s.close()


def parse_status(resp):
    """Parse 'pulse status' output -> dict(freq, a_on, a_duty, b_on, b_duty)."""
    out = {}
    m = re.search(r"Frequency\s*=\s*([\d.]+)\s*Hz", resp)
    out["freq"] = float(m.group(1)) if m else None
    for ch, key in (("A", "a"), ("B", "b")):
        m = re.search(rf"{ch}\s*\(RC\d\):\s*(ON|OFF),\s*duty\s*([\d.]+)\s*%", resp)
        out[f"{key}_on"] = (m.group(1) == "ON") if m else None
        out[f"{key}_duty"] = float(m.group(2)) if m else None
    return out


# ============================ Saleae capture =========================
def saleae_capture(manager, channels, sample_rate, duration, outdir,
                   device_id=None):
    from saleae import automation
    dev = automation.LogicDeviceConfiguration(
        enabled_digital_channels=list(channels),
        digital_sample_rate=sample_rate,
    )
    cap_cfg = automation.CaptureConfiguration(
        capture_mode=automation.TimedCaptureMode(duration_seconds=duration))
    os.makedirs(outdir, exist_ok=True)
    capture = manager.start_capture(device_id=device_id,
                                    device_configuration=dev,
                                    capture_configuration=cap_cfg)
    try:
        capture.wait()
        capture.export_raw_data_csv(directory=outdir,
                                    digital_channels=list(channels))
    finally:
        capture.close()
    return os.path.join(outdir, "digital.csv")


# ============================ Test runner ============================
TEST_CASES = [
    # freq Hz, duty A %, duty B %
    dict(freq=1000,  duty_a=25.0, duty_b=75.0),
    dict(freq=5000,  duty_a=10.0, duty_b=50.0),
    dict(freq=20000, duty_a=33.3, duty_b=66.7),
    dict(freq=1000,  duty_a=50.0, duty_b=0.0, b_off=True),  # B disabled -> low
]


def _check(measured, expected, tol, unit, what, checks, rows):
    ok = abs(measured - expected) <= tol
    checks.append(Check(what, ok,
                        f"measured {measured:.3f}{unit}, expected {expected:.3f}{unit} "
                        f"(tol {tol}{unit})"))
    rows.append([what, f"{measured:.3f}{unit}", f"{expected:.3f}{unit}",
                 f"{tol}{unit}", "PASS" if ok else "FAIL"])
    print(f"      [{'PASS' if ok else 'FAIL'}] {what}: measured {measured:.3f}{unit}, "
          f"expected {expected:.3f}{unit} (tol {tol}{unit})")
    return ok


def run_case(console, manager, case, sample_rate, base_outdir, device_id, idx) -> Result:
    f = case["freq"]
    da, db = case["duty_a"], case["duty_b"]
    a_off, b_off = case.get("a_off", False), case.get("b_off", False)
    name = (f"{f} Hz, A={da}% ({'off' if a_off else 'on'}), "
            f"B={db}% ({'off' if b_off else 'on'})")
    print(f"\n--- Test {idx}: {name} ---")

    console.cmd(f"pulse freq {f}")
    console.cmd(f"pulse a duty {da}")
    console.cmd(f"pulse b duty {db}")
    console.cmd("pulse a off" if a_off else "pulse a on")
    console.cmd("pulse b off" if b_off else "pulse b on")
    st = parse_status(console.cmd("pulse status"))

    duration = max(0.05, 80.0 / f)
    outdir = os.path.join(base_outdir, f"test{idx}")
    csv_path = saleae_capture(manager, [RC0_CH, RC1_CH], sample_rate,
                              duration, outdir, device_id)
    m0 = analyze_digital_csv(csv_path, RC0_CH)
    m1 = analyze_digital_csv(csv_path, RC1_CH)
    print(f"      RC0 measured: {m0['freq_hz']:.1f} Hz, {m0['duty_pct']:.2f}% "
          f"({m0['cycles']} cycles)")
    print(f"      RC1 measured: {m1['freq_hz']:.1f} Hz, {m1['duty_pct']:.2f}% "
          f"({m1['cycles']} cycles)")

    checks, rows = [], []
    for ch, m, duty, off, lbl in ((RC0_CH, m0, st["a_duty"], a_off, "RC0"),
                                  (RC1_CH, m1, st["b_duty"], b_off, "RC1")):
        if off:
            ok = (m["cycles"] == 0 and m["level"] == 0)
            checks.append(Check(f"{lbl} disabled -> line low", ok,
                                f"level={m['level']}, cycles={m['cycles']}"))
            rows.append([f"{lbl} disabled", f"level {m['level']}", "low", "-",
                         "PASS" if ok else "FAIL"])
        else:
            _check(m["freq_hz"], st["freq"], st["freq"] * FREQ_TOL, " Hz", f"{lbl} freq", checks, rows)
            _check(m["duty_pct"], duty, DUTY_TOL, " %", f"{lbl} duty", checks, rows)

    return Result(name, all(c.passed for c in checks),
                  f"firmware freq {st['freq']:.1f} Hz; RC0/RC1 measured on the pin",
                  checks, ["Check", "measured", "expected (firmware)", "tol", "result"], rows)


def test_duty_hold(console, manager, sample_rate, base_outdir, device_id) -> Result:
    """Duty must stay constant when the frequency changes (firmware rescales DC)."""
    duty = 30.0
    freqs = [1000, 5000, 20000]
    print(f"\n--- Duty held at {duty}% across {freqs} Hz ---")
    console.cmd(f"pulse a duty {duty}")
    console.cmd("pulse a on")
    checks, rows = [], []
    for i, f in enumerate(freqs):
        console.cmd(f"pulse freq {f}")
        fw = parse_status(console.cmd("pulse status"))["a_duty"]
        duration = max(0.05, 80.0 / f)
        csv_path = saleae_capture(manager, [RC0_CH], sample_rate, duration,
                                  os.path.join(base_outdir, f"hold{i}"), device_id)
        meas = analyze_digital_csv(csv_path, RC0_CH)["duty_pct"]
        ok = abs(meas - duty) <= DUTY_TOL
        checks.append(Check(f"duty at {f} Hz", ok,
                            f"measured {meas:.2f}% (set {duty}%, firmware {fw:.2f}%)"))
        rows.append([f"{f} Hz", f"{meas:.2f}%", f"{fw:.2f}%", f"{duty}%",
                     "PASS" if ok else "FAIL"])
        print(f"      [{'PASS' if ok else 'FAIL'}] {f} Hz: measured {meas:.2f}% "
              f"(firmware {fw:.2f}%)")
    return Result(f"Duty held at {duty}% across frequencies",
                  all(c.passed for c in checks),
                  "changing frequency must not disturb the duty cycle",
                  checks, ["Frequency", "measured", "firmware", "set", "result"], rows)


def test_channel_independence(console, manager, sample_rate, base_outdir, device_id) -> Result:
    """The channels share the frequency but their duty and on/off must be
    independent: changing or disabling one must not disturb the other.
    Both pins are captured simultaneously at each step."""
    f = 5000
    console.cmd(f"pulse freq {f}")
    duration = max(0.05, 80.0 / f)
    print(f"\n--- Channel independence at {f} Hz ---")

    steps = [
        # name,                          da, db, a_on,  b_on
        ("baseline A=25% B=75%",         25, 75, True,  True),
        ("change A->80%, B stays 75%",   80, 75, True,  True),
        ("change B->10%, A stays 80%",   80, 10, True,  True),
        ("A off, B stays 10%",           80, 10, False, True),
        ("B off, A stays 80%",           80, 10, True,  False),
    ]

    checks, rows = [], []
    for i, (name, da, db, a_on, b_on) in enumerate(steps):
        console.cmd(f"pulse a duty {da}")
        console.cmd(f"pulse b duty {db}")
        console.cmd("pulse a on" if a_on else "pulse a off")
        console.cmd("pulse b on" if b_on else "pulse b off")
        csv = saleae_capture(manager, [RC0_CH, RC1_CH], sample_rate, duration,
                             os.path.join(base_outdir, f"indep{i}"), device_id)
        mA = analyze_digital_csv(csv, RC0_CH)
        mB = analyze_digital_csv(csv, RC1_CH)

        okA = (abs(mA["duty_pct"] - da) <= DUTY_TOL) if a_on \
            else (mA["cycles"] == 0 and mA["level"] == 0)
        okB = (abs(mB["duty_pct"] - db) <= DUTY_TOL) if b_on \
            else (mB["cycles"] == 0 and mB["level"] == 0)
        ok = okA and okB
        a_str = f"{mA['duty_pct']:.1f}%" if a_on else f"low(cyc={mA['cycles']})"
        b_str = f"{mB['duty_pct']:.1f}%" if b_on else f"low(cyc={mB['cycles']})"
        checks.append(Check(name, ok, f"RC0={a_str}, RC1={b_str}"))
        rows.append([name, f"{da}%" if a_on else "off", a_str,
                     f"{db}%" if b_on else "off", b_str, "PASS" if ok else "FAIL"])
        print(f"      [{'PASS' if ok else 'FAIL'}] {name}: RC0={a_str}, RC1={b_str}")

    return Result("Channel independence (RC0 vs RC1)",
                  all(c.passed for c in checks),
                  "duty and on/off are per-channel; one must not disturb the other",
                  checks, ["Step", "set A", "meas RC0", "set B", "meas RC1", "result"], rows)


def run_suite(console, manager, device_id, sample_rate, base_outdir) -> Suite:
    """Run all Saleae smoke-test cases and return a Suite of Results."""
    os.makedirs(base_outdir, exist_ok=True)
    suite = Suite("Smoke test (Saleae)",
                  "PWM frequency and duty measured directly on RC0/RC1.")
    for i, case in enumerate(TEST_CASES, 1):
        suite.add(run_case(console, manager, case, sample_rate, base_outdir, device_id, i))
    suite.add(test_duty_hold(console, manager, sample_rate, base_outdir, device_id))
    suite.add(test_channel_independence(console, manager, sample_rate, base_outdir, device_id))
    return suite


# ===================== Half-bridge (CLB) test ========================
HB_DT_TOL_NS = 35.0      # dead-time must land within ~1 tick (31.25 ns) of commanded
HB_OVL_TOL_NS = 20.0     # both-high (shoot-through) must be essentially zero


def run_halfbridge_suite(console, manager, device_id, base_outdir):
    """Sweep the CLB half-bridge over frequency x dead-time, measure HS/LS on
    RC0/RC1, and return (Suite, images). Reuses clb_hb_report's measurement,
    analysis and plotting so the report carries the same data and diagrams."""
    import clb_hb_report as hb            # lazy: avoids the smoketest<->clb_hb_report cycle
    from clb_halfbridge_test import _read_states
    os.makedirs(base_outdir, exist_ok=True)

    console.cmd("reset"); time.sleep(1.0)  # clear sticky CLB state (documented)
    rows, wave = [], None
    for code, fhz in hb.FREQS:
        for dt in hb.DTS:
            console.cmd("clb off"); console.cmd(f"clb freq {code}")
            console.cmd(f"clb dt {dt}"); console.cmd("clb on"); time.sleep(0.05)
            path = saleae_capture(manager, [RC0_CH, RC1_CH], hb.RATE, 0.005,
                                  os.path.join(base_outdir, f"hb_f{code}_dt{dt}"), device_id)
            st = _read_states(path)
            a = hb.analyze(st)
            a.update(code=code, fnom=fhz, dt=dt, dt_nom=dt * hb.TICK_NS)
            rows.append(a)
            print(f"      HB f{code}({fhz}Hz) dt{dt}: f={a['freq']/1e3:.1f}k "
                  f"dead={a['dt_med']:.0f}ns(nom {dt*hb.TICK_NS:.0f}) ovl={a['overlap_ns']:.0f}ns")
            if (code, dt) == hb.WAVE:
                wave = st
    console.cmd("clb off")

    # ---- build the Suite: one Result per carrier frequency, dt sweep inside ----
    suite = Suite("Half-bridge (CLB)",
                  "Complementary HS (RC0) / LS (RC1) with runtime dead-time. Dead-time "
                  "should track dt x 31.25 ns; the two sides must never overlap.")
    for code, fhz in hb.FREQS:
        sub = [r for r in rows if r["code"] == code]
        favg = statistics.mean(r["freq"] for r in sub)
        freq_ok = abs(favg - fhz) <= fhz * FREQ_TOL
        dt_ok = all(abs(r["dt_med"] - r["dt_nom"]) <= HB_DT_TOL_NS for r in sub)
        ovl_ok = all(r["overlap_ns"] <= HB_OVL_TOL_NS for r in sub)
        checks = [
            Check(f"carrier {fhz/1000:.1f} kHz within {FREQ_TOL*100:.0f}%", freq_ok,
                  f"measured {favg/1e3:.2f} kHz"),
            Check("dead-time within ~1 tick (31.25 ns) of commanded, every step", dt_ok,
                  "max err %.0f ns" % max(abs(r["dt_med"]-r["dt_nom"]) for r in sub)),
            Check("no shoot-through (both-high ~ 0) at every step", ovl_ok,
                  "max overlap %.0f ns" % max(r["overlap_ns"] for r in sub)),
        ]
        trows = [[r["dt"], f"{r['dt_nom']:.0f}", f"{r['dt_med']:.0f}",
                  f"{r['dt_med']-r['dt_nom']:+.0f}", f"{r['overlap_ns']:.0f}",
                  f"{r['freq']/1e3:.2f}", f"{r['duty_hs']*100:.1f}",
                  "PASS" if (abs(r['dt_med']-r['dt_nom'])<=HB_DT_TOL_NS and
                             r['overlap_ns']<=HB_OVL_TOL_NS) else "FAIL"] for r in sub]
        suite.add(Result(
            f"{fhz/1000:.1f} kHz carrier - dead-time sweep",
            freq_ok and dt_ok and ovl_ok,
            f"dt {hb.DTS[0]}..{hb.DTS[-1]} ticks; carrier {favg/1e3:.2f} kHz measured",
            checks,
            ["clb dt", "nom [ns]", "meas [ns]", "err [ns]", "overlap [ns]", "freq [kHz]",
             "HS duty [%]", "result"], trows))

    # ---- plots as self-contained data URIs (reuse clb_hb_report's plotters) ----
    def uri(b64):
        return "data:image/png;base64," + b64
    images = []
    if os.path.exists(hb.BLOCKDIAG):
        images.append(("Block diagram - CLB counter + TMR2 dead-time + CLC gating",
                       uri(hb._file_b64(hb.BLOCKDIAG))))
    images += [
        ("Dead-time: measured vs. commanded (linearity)", uri(hb.plot_linearity(rows))),
        ("Dead-time error vs. commanded value", uri(hb.plot_error(rows))),
        ("Shoot-through overlap across all settings", uri(hb.plot_overlap(rows))),
    ]
    if wave:
        images.append(("HS/LS waveforms + dead-time zoom", uri(hb.plot_wave(wave))))
    return suite, images


def run_hardware(args):
    from saleae import automation
    print(f"Opening serial console on {args.port} ...")
    console = Console(args.port, echo=not args.quiet_cli)
    banner = console.cmd("version")
    print(f"  {banner.strip().splitlines()[-2] if banner.strip() else '(no banner)'}")

    print("Connecting to Logic 2 automation ...")
    manager = automation.Manager.connect(port=args.automation_port)
    device_id = args.device_id
    if device_id is None:
        devs = manager.get_devices()
        if not devs:
            print("ERROR: no Saleae device found in Logic 2.")
            return 1
        device_id = devs[0].device_id
        print(f"  using device {device_id} ({devs[0].device_type})")

    suites, images = [], []
    try:
        if not args.no_regression:
            print("\n=== CLI regression (serial only) ===")
            import regression                 # lazy: regression imports Console from us
            suites.append(regression.run(console))   # ends by rebooting the device
        if not args.no_pwm:
            suites.append(run_suite(console, manager, device_id, args.sample_rate, args.csv_dir))
        if not args.no_halfbridge:
            print("\n=== Half-bridge (CLB) frequency x dead-time sweep ===")
            try:
                hb_suite, images = run_halfbridge_suite(
                    console, manager, device_id, os.path.join(args.csv_dir, "halfbridge"))
                suites.append(hb_suite)
            except Exception as e:
                s = Suite("Half-bridge (CLB)", "frequency x dead-time sweep")
                s.skipped = True; s.skip_reason = f"half-bridge test error: {e}"
                suites.append(s)
                print(f"  half-bridge test skipped: {e}")
    finally:
        console.close()
        manager.close()

    meta = {"Device": "PIC16F13145 Curiosity Nano", "Port": args.port,
            "Sample rate": f"{args.sample_rate/1e6:.0f} MS/s (PWM), 100 MS/s (half-bridge)"}
    overall = write_html(args.report, "Loop - PWM & Half-Bridge Smoke Test",
                         meta, suites, images=images or None)
    print(f"\nreport written: {args.report}")
    for s in suites:
        n = len(s.results); npass = sum(1 for r in s.results if r.passed)
        tag = "SKIP" if s.skipped else f"{npass}/{n}"
        print(f"  [{'PASS' if s.passed else ('SKIP' if s.skipped else 'FAIL')}] {s.name}: {tag}")
    print(f"================  OVERALL: {'PASS' if overall else 'FAIL'}  ================")
    return 0 if overall else 1


# ============================ Offline modes ==========================
def run_analyze(path):
    if os.path.isdir(path):
        path = os.path.join(path, "digital.csv")
    print(f"Analysing {path}")
    for ch, name in ((RC0_CH, "RC0"), (RC1_CH, "RC1")):
        m = analyze_digital_csv(path, ch)
        print(f"  {name} (ch{ch}): {m['freq_hz']:.3f} Hz, "
              f"{m['duty_pct']:.3f} %, {m['cycles']} cycles, level={m['level']}")
    return 0


def _write_synthetic_csv(path, freq, duty_a, duty_b, cycles=50):
    """Generate a Saleae-style transition CSV for two PWM channels."""
    period = 1.0 / freq
    ev = {}  # time -> {ch: level}
    for ch, duty in ((0, duty_a), (1, duty_b)):
        for k in range(cycles):
            t0 = k * period
            ev.setdefault(round(t0, 9), {})[ch] = 1
            ev.setdefault(round(t0 + period * duty / 100.0, 9), {})[ch] = 0
    state = {0: 0, 1: 0}
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time [s]", "Channel 0", "Channel 1"])
        w.writerow([f"{0.0:.9f}", 0, 0])
        for t in sorted(ev):
            state.update(ev[t])
            w.writerow([f"{t:.9f}", state[0], state[1]])


def run_selftest(args):
    import tempfile
    tmp = tempfile.mkdtemp(prefix="loop_smoke_")
    path = os.path.join(tmp, "digital.csv")
    cases = [(1000.0, 30.0, 60.0), (20000.0, 12.5, 87.5)]
    ok = True
    for freq, da, db in cases:
        _write_synthetic_csv(path, freq, da, db)
        m0 = analyze_digital_csv(path, 0)
        m1 = analyze_digital_csv(path, 1)
        print(f"synthetic freq={freq} da={da} db={db}")
        print(f"  ch0 -> {m0['freq_hz']:.2f} Hz, {m0['duty_pct']:.3f} %")
        print(f"  ch1 -> {m1['freq_hz']:.2f} Hz, {m1['duty_pct']:.3f} %")
        for got, exp, tol, what in (
            (m0["freq_hz"], freq, freq * 0.001, "ch0 freq"),
            (m1["freq_hz"], freq, freq * 0.001, "ch1 freq"),
            (m0["duty_pct"], da, 0.05, "ch0 duty"),
            (m1["duty_pct"], db, 0.05, "ch1 duty"),
        ):
            if abs(got - exp) > tol:
                print(f"  FAIL {what}: {got} vs {exp}")
                ok = False
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Saleae smoke test for Loop PWM firmware")
    ap.add_argument("--port", default=project_config.flasher_port(),
                    help="serial port of the PIC console")
    ap.add_argument("--sample-rate", type=int, default=10_000_000,
                    help="Saleae digital sample rate in S/s (default 10 MS/s)")
    ap.add_argument("--csv-dir", default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "smoketest_csv"),
                    help="directory for the exported digital.csv files")
    ap.add_argument("--device-id", default=None, help="Saleae device id (default: first found)")
    ap.add_argument("--automation-port", type=int, default=10430)
    ap.add_argument("--quiet-cli", action="store_true",
                    help="do not echo the serial commands/responses")
    ap.add_argument("--report", default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "smoketest_report.html"),
                    help="output HTML report (PWM + half-bridge + plots)")
    ap.add_argument("--no-halfbridge", action="store_true",
                    help="skip the CLB half-bridge frequency/dead-time sweep")
    ap.add_argument("--no-pwm", action="store_true",
                    help="skip the plain-PWM smoke cases (half-bridge only)")
    ap.add_argument("--no-regression", action="store_true",
                    help="skip the serial-only CLI regression suite")
    ap.add_argument("--analyze", metavar="CSV_OR_DIR",
                    help="only analyse an existing digital.csv (no hardware)")
    ap.add_argument("--selftest", action="store_true",
                    help="validate the analyser with synthetic data (no hardware)")
    args = ap.parse_args()

    if args.selftest:
        return run_selftest(args)
    if args.analyze:
        return run_analyze(args.analyze)
    return run_hardware(args)


if __name__ == "__main__":
    sys.exit(main())
