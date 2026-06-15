#!/usr/bin/env python3
"""
clb_analyze.py - CLB capability characterization suite (PIC16F13145).

Runs a catalog of minimal Verilog designs (clb/catalog/<name>/) through two gates
to build an evidence-based map of what the on-chip CLB can and cannot do:

  Gate A - synthesis / place-and-route  (software, fast):  does it route? words?
  Gate B - silicon  (build -> flash -> Saleae on RC0..RC3): does it actually work?

Per-design verdict: ROUTE_FAIL / HW_DEAD / WORKS / WRONG. All four wired channels
(RC0->D0, RC1->D1, RC2->D2, RC3->D3) are used; input designs drive PWM1 onto RC3 and
read it into the CLB via CLBIN0PPS (`clbraw in`), software-input designs drive CLBSWIN
from the CLI (`clbsw`). Result -> clb_capability_report.html.

Usage:
  python clb_analyze.py                 # full run (synth+build+flash+measure)
  python clb_analyze.py --gate-a-only   # synthesis only, no hardware
  python clb_analyze.py --only counter_2tap,comb_basic
  python clb_analyze.py --host local --sample-rate 50000000
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

import project_config
from run_ci import run_build, run_flash
from smoketest import Console, saleae_capture, analyze_digital_csv
from testreport import Suite, Result, Check, write_html

ROOT = os.path.dirname(os.path.abspath(__file__))
SYNTH = os.path.join(ROOT, "clb", "synth.py")
CATALOG_DIR = os.path.join(ROOT, "clb", "catalog")
BITSTREAM = os.path.join(ROOT, "clbBitstream.S")
DEFS = os.path.join(ROOT, "clb1_defs.h")
CSV_DIR = os.path.join(ROOT, "clb_cap_csv")
BLE = 32_000_000.0          # measured BLE_clk (FOSC)
FTOL = 0.06                 # frequency tolerance
PWM_IN = 50_000             # stimulus PWM frequency for `in` designs


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


# ---- per-channel capture -> {ch: dict(freq_hz, level, duty_pct)} ----
def measure(manager, device_id, sample_rate, seconds, tag, channels=(0, 1, 2, 3)):
    outdir = os.path.join(CSV_DIR, tag)
    path = saleae_capture(manager, list(channels), sample_rate, seconds, outdir, device_id)
    return {ch: analyze_digital_csv(path, ch) for ch in channels}


def fhz(m, ch):
    return m[ch]["freq_hz"]


def near(meas, want, tol=FTOL):
    return want > 0 and abs(meas - want) <= tol * want


# =========================== probe builders ===========================
# Each probe is f(console, manager, device_id, rate) -> (verdict, detail).

def probe_freq(expect, fixture="on"):
    """expect: {ch: hz}. WORKS if every listed channel hits its frequency."""
    def run(console, manager, device_id, rate):
        _fixture(console, fixture)
        m = measure(manager, device_id, rate, 0.005, "freq")
        parts, ok_all, dead_all = [], True, True
        for ch, want in expect.items():
            got = fhz(m, ch)
            ok = near(got, want)
            ok_all &= ok
            if got > 100:  # toggling at all
                dead_all = False
            parts.append(f"D{ch} {got/1000:.1f}k (want {want/1000:.1f}k){'' if ok else ' X'}")
        verdict = "WORKS" if ok_all else ("HW_DEAD" if dead_all else "WRONG")
        return verdict, "; ".join(parts)
    return run


def probe_truth(vectors, nout, fixture="on"):
    """vectors: [(swin_hex, [exp_levels...])]. Reads the static level per channel."""
    def run(console, manager, device_id, rate):
        _fixture(console, fixture)
        rows, ok_all, changed = [], True, set()
        for sw, exp in vectors:
            console.cmd(f"clbsw {sw}")
            m = measure(manager, device_id, 1_000_000, 0.003, f"sw{sw}")
            got = [m[ch]["level"] for ch in range(nout)]
            for ch in range(nout):
                changed.add((ch, got[ch]))
            match = (got == exp)
            ok_all &= match
            rows.append(f"{sw}->{got}(want {exp}){'' if match else ' X'}")
        # if no output ever changed across vectors, it's unresponsive/dead
        per_ch_levels = {}
        for ch, v in changed:
            per_ch_levels.setdefault(ch, set()).add(v)
        responsive = any(len(vs) > 1 for vs in per_ch_levels.values())
        verdict = "WORKS" if ok_all else ("HW_DEAD" if not responsive else "WRONG")
        return verdict, " | ".join(rows)
    return run


def probe_gate(ref_ch, gated_ch, ref_hz, fixture, has_swin):
    """Wall test: a reference (raw counter / raw PWM) on ref_ch and a gated copy on
    gated_ch. Confirms whether the gated/combined construct keeps the source alive."""
    def run(console, manager, device_id, rate):
        _fixture(console, fixture)
        detail = []
        if has_swin:
            console.cmd("clbsw 0x01")           # gate open
        m1 = measure(manager, device_id, rate, 0.005, "gate_open")
        ref = fhz(m1, ref_ch); gated = fhz(m1, gated_ch)
        detail.append(f"open: ref D{ref_ch} {ref/1000:.1f}k, gated D{gated_ch} {gated/1000:.1f}k")
        ref_ok = near(ref, ref_hz)
        gate_works = gated > 100
        if has_swin:
            console.cmd("clbsw 0x00")           # gate closed -> gated should go static
            m0 = measure(manager, device_id, rate, 0.005, "gate_closed")
            g0 = fhz(m0, gated_ch)
            detail.append(f"closed: gated D{gated_ch} {g0/1000:.1f}k")
            gate_works = gate_works and (g0 < 100)
        if not ref_ok:
            verdict = "HW_DEAD"   # the source (counter) itself did not run -> the wall
        elif gate_works:
            verdict = "WORKS"
        else:
            verdict = "WRONG"
        return verdict, "; ".join(detail)
    return run


def _fixture(console, fixture):
    if fixture == "in":
        console.cmd(f"pulse freq {PWM_IN}")
        console.cmd("pulse a on")
        console.cmd("clbraw in")
    else:
        console.cmd("clbraw on")


# =============================== catalog ===============================
# expect_fail: a design we predict will NOT route (documents a limit).
CATALOG = [
    # --- counters (registered, clocked) ---
    dict(name="counter_2tap", cat="counter", hw=probe_freq({0: 125000, 1: 62500}),
         note="2 octave taps cnt[7]/cnt[8] -> 2 outputs (the proven baseline)"),
    dict(name="counter_3tap", cat="counter", hw=probe_freq({0: 125000, 1: 62500, 2: 31250}),
         note="3 high-bit taps -> 3 outputs (tests the multi-output routing limit)"),
    dict(name="counter_4tap", cat="counter",
         hw=probe_freq({0: 250000, 1: 125000, 2: 62500, 3: 31250}),
         note="4 taps -> all four pins at once"),
    dict(name="counter_w12", cat="counter", hw=probe_freq({0: 7812, 1: 500000}),
         note="12-bit counter, high + mid tap"),
    dict(name="two_counters", cat="counter", hw=probe_freq({0: 125000, 1: 250000}),
         note="two independent always-blocks (parallel sequential)"),
    # --- combinational (registered) via CLBSWIN ---
    dict(name="comb_basic", cat="combinational",
         hw=probe_truth([("0x00", [0, 0, 0, 1]), ("0x01", [0, 1, 1, 0]),
                         ("0x02", [0, 1, 1, 1]), ("0x03", [1, 1, 0, 0])], 4),
         note="AND / OR / XOR / NOT of two software inputs"),
    dict(name="comb_and8", cat="combinational",
         hw=probe_truth([("0x00", [0, 0]), ("0x01", [0, 1]),
                         ("0x7f", [0, 1]), ("0xff", [1, 1])], 2),
         note="8-input AND / OR (LUT width)"),
    dict(name="comb_mux", cat="combinational",
         hw=probe_truth([("0x00", [0, 0]), ("0x03", [1, 0]),
                         ("0x04", [0, 0]), ("0x05", [1, 0]), ("0x07", [1, 1])], 2),
         note="2:1 mux (sw2 ? sw0 : sw1) + 3-input AND"),
    dict(name="swin_reg", cat="combinational",
         hw=probe_truth([("0x00", [0, 0, 0, 0]), ("0x05", [1, 0, 1, 0]),
                         ("0x0a", [0, 1, 0, 1]), ("0x0f", [1, 1, 1, 1])], 4),
         note="pure CLBSWIN passthrough -> 4 outputs (software-input characterization)"),
    # --- async (predicted route failure: must register through the BLE flop) ---
    dict(name="async_pass", cat="async", hw=None, expect_fail=True,
         note="pure combinational, NO clock/flop -> expected to fail P&R"),
    # --- pin input (registered) via CLBIN0PPS ---
    dict(name="in_reg", cat="input", hw=probe_freq({0: PWM_IN, 1: PWM_IN}, fixture="in"),
         note="pin input (PWM on RC3) -> o0=IN0, o1=~IN0"),
    dict(name="in_gate_swin", cat="input",
         hw=probe_gate(ref_ch=1, gated_ch=0, ref_hz=PWM_IN, fixture="in", has_swin=True),
         note="o0 = IN0 & sw0 (input gated by software bit), o1 = IN0 reference"),
    # --- the combination wall ---
    dict(name="cnt_gate_swin", cat="wall",
         hw=probe_gate(ref_ch=1, gated_ch=0, ref_hz=125000, fixture="on", has_swin=True),
         note="counter + (cnt[7] & sw0): does the counter survive gating? (the wall)"),
    dict(name="cnt_gate_in", cat="wall",
         hw=probe_gate(ref_ch=1, gated_ch=0, ref_hz=125000, fixture="in", has_swin=False),
         note="counter + (cnt[7] & IN0): counter + input + gate combined"),
    # --- sequential depth ---
    dict(name="shift4", cat="sequential", hw=probe_freq({0: PWM_IN, 1: PWM_IN}, fixture="in"),
         note="4-stage shift register of the pin input (does multi-flop delay form?)"),
]


# ============================== gate A =================================
def gate_a(name, host):
    d = os.path.join(CATALOG_DIR, name)
    p = subprocess.run([sys.executable, SYNTH, "--host", host, "--indir", d],
                       cwd=ROOT, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"OK:\s*(\d+)\s*bitstream words", out)
    words = int(m.group(1)) if m else 0
    routes = (p.returncode == 0) and words > 0
    err = ""
    if not routes:
        if "could not be routed" in out:
            err = "clock could not be routed"
        elif "failed to route" in out:
            err = "VPR failed to route"
        else:
            err = (out.strip().splitlines() or ["failed"])[-1][:80]
    return routes, words, err


# ================================ main =================================
def main():
    ap = argparse.ArgumentParser(description="CLB capability characterization suite")
    ap.add_argument("--host", default="cont")
    ap.add_argument("--only", default=None, help="comma-separated design names")
    ap.add_argument("--gate-a-only", action="store_true")
    ap.add_argument("--sample-rate", type=int, default=50_000_000)
    ap.add_argument("--port", default=project_config.flasher_port())
    ap.add_argument("--automation-port", type=int, default=10430)
    ap.add_argument("--out", default=os.path.join(ROOT, "clb_capability_report.html"))
    args = ap.parse_args()

    catalog = CATALOG
    if args.only:
        want = set(args.only.split(","))
        catalog = [d for d in CATALOG if d["name"] in want]

    # back up the working half-bridge bitstream; restore on exit
    bak = None
    if os.path.exists(BITSTREAM):
        bak = (BITSTREAM + ".bak", DEFS + ".bak")
        shutil.copyfile(BITSTREAM, bak[0])
        if os.path.exists(DEFS):
            shutil.copyfile(DEFS, bak[1])

    manager = device_id = None
    suite = Suite("CLB capability characterization",
                  "Each design isolates one CLB feature and is graded through two gates: "
                  "Gate A = synthesis/P&R (does it route), Gate B = silicon (Saleae on "
                  "RC0..RC3, does it behave). Verdict: WORKS / HW_DEAD / WRONG / ROUTE_FAIL.")
    rows = []
    try:
        if not args.gate_a_only:
            from saleae import automation
            manager = automation.Manager.connect(port=args.automation_port)
            devs = manager.get_devices()
            if not devs:
                log("no Saleae device; falling back to gate-A-only")
                args.gate_a_only = True
            else:
                device_id = devs[0].device_id

        for d in catalog:
            name = d["name"]
            log(f"===== {name} ({d['cat']}) =====")
            routes, words, err = gate_a(name, args.host)
            log(f"  gate A: {'ROUTES '+str(words)+'w' if routes else 'FAIL ('+err+')'}")
            if not routes:
                verdict, detail = "ROUTE_FAIL", err
            else:
                verdict, detail = "ROUTES", f"{words} words"
                if d.get("expect_fail"):
                    verdict = "WRONG(routed)"      # predicted not to route, but did
                if not args.gate_a_only and d["hw"] is not None:
                    log("  build...")
                    br = run_build()
                    if not br.passed:                # build.bat is occasionally flaky
                        log("  build retry...")
                        br = run_build()
                    if br.passed:
                        log("  flash...")
                        fr = run_flash()
                        if fr.passed:
                            console = Console(args.port, echo=False)
                            try:
                                verdict, detail = d["hw"](console, manager, device_id, args.sample_rate)
                            finally:
                                console.cmd("clbraw off"); console.cmd("pulse a off"); console.close()
                            log(f"  gate B: {verdict} ({detail})")
                        else:
                            verdict, detail = "FLASH_FAIL", "flash failed"
                    else:
                        verdict, detail = "BUILD_FAIL", "build failed: " + br.summary

            # pass = clean expected result. expect_fail designs pass when they DON'T route.
            if d.get("expect_fail"):
                passed = (verdict == "ROUTE_FAIL")
            elif args.gate_a_only or d["hw"] is None:
                passed = routes
            else:
                passed = (verdict == "WORKS")
            checks = [Check(d["note"], passed, detail)]
            rows.append([d["cat"], name, ("yes/" + str(words)) if routes else "NO",
                         verdict, detail[:60]])
            suite.add(Result(f"{name}", passed,
                             f"[{d['cat']}] {verdict} - {d['note']}", checks))
    finally:
        if manager is not None:
            manager.close()
        # restore the half-bridge bitstream so `clb on` still works afterwards
        if bak and os.path.exists(bak[0]):
            shutil.copyfile(bak[0], BITSTREAM); os.remove(bak[0])
            if os.path.exists(bak[1]):
                shutil.copyfile(bak[1], DEFS); os.remove(bak[1])
            log("restored half-bridge clbBitstream.S")

    # summary table as its own result
    summary = Result("Capability matrix", True, f"{len(rows)} designs",
                     [], ["category", "design", "routes/words", "verdict", "detail"], rows)
    suite.add(summary)
    meta = {"Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Device": "PIC16F13145", "BLE_clk": "32 MHz",
            "Channels": "RC0->D0, RC1->D1, RC2->D2, RC3->D3",
            "Mode": "gate A only" if args.gate_a_only else "gate A + B (hardware)"}
    write_html(args.out, "CLB Capability Characterization", meta, [suite])
    log(f"report: {args.out}")
    # verdict tally
    tally = {}
    for r in rows:
        tally[r[3]] = tally.get(r[3], 0) + 1
    log("tally: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
