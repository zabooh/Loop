#!/usr/bin/env python3
"""
clb_hil.py - hardware-in-the-loop driver for CLB designs (PIC16F13145).

Closes the full loop for a CLB logic task:

    design (Verilog)  ->  synthesize (clb/synth.py -> bitstream + length header)
                      ->  build      (build.bat, XC8 assembles the bitstream in)
                      ->  flash       (flash.py / MPLAB MDB over ICSP)
                      ->  test        (clb_halfbridge_test.py, Saleae on RC0/RC1)
                      ->  if it fails, change the design and start over.

The "change the design and start over" step is automated for the one parameter
that can only be resolved against real silicon: the CLB *input mux code* that
routes PWM1 into the design. The driver synthesizes/builds/flashes a candidate,
checks on the Saleae whether the half-bridge output actually follows the PWM
input, and if not moves on to the next candidate - a genuine hardware search.
(Structural redesign of the Verilog itself remains a human/agent step; this
driver is the mechanical loop around it.)

Everything is recorded into a single HTML report (clb_hil_report.html): every
iteration's synthesis word count, build memory, flash result and measurements,
plus the final detailed half-bridge test (non-overlap + dead-time sweep).

Usage:
  python clb_hil.py                     # search the input mux, full HIL run + report
  python clb_hil.py --mux 47            # force one mux code (no search)
  python clb_hil.py --candidates 47,48,46
  python clb_hil.py --skip-build        # reuse the flashed firmware (no synth/build/flash)
  python clb_hil.py --host local        # synth against a local Docker backend
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime

from testreport import Suite, Result, Check, write_html
import project_config
from run_ci import run_build, run_flash
import clb_halfbridge_test as hbtest

ROOT = os.path.dirname(os.path.abspath(__file__))
SYNTH = os.path.join(ROOT, "clb", "synth.py")
LOG_PATH = os.path.join(ROOT, "clb_hil.log")

# Live progress log: every line is timestamped, printed (flushed) AND appended to
# clb_hil.log so you can watch what the tool is doing with `tail -f clb_hil.log`.
import time
_LOG_FH = None


def log(msg, stage=None):
    line = time.strftime("[%H:%M:%S]") + (f" [{stage}] " if stage else " ") + msg
    print(line, flush=True)
    if _LOG_FH:
        _LOG_FH.write(line + "\n"); _LOG_FH.flush()

# PWM1 input-mux candidates (7-bit CLB input-selection codes). 47 = PWM1_OUT per
# the CLC/CLB input-selection table; the rest are nearby fallbacks the hardware
# search tries if 47 turns out not to route PWM1 into the CLB on this device.
SEARCH_CANDIDATES = [47, 48, 46, 49, 45, 50, 44]

TASK = ("Half-bridge on RC0 (high-side) / RC1 (low-side) from one PWM input, "
        "with a non-overlap dead-time adjustable at run time via `clb dt`.")


def run_synth(mux, host):
    """Synthesize clb_halfbridge.v with the given input-mux code. Returns (Result, words)."""
    log(f"synthesize clb_halfbridge.v with IN0 mux=7'd{mux} (backend {host}) ...", "SYNTH")
    p = subprocess.run([sys.executable, SYNTH, "--host", host, "--mux", str(mux)],
                       cwd=ROOT, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"OK:\s*(\d+)\s*bitstream words", out)
    words = int(m.group(1)) if m else 0
    ok = (p.returncode == 0) and words > 0
    detail = f"{words} words, IN0 mux=7'd{mux}" if ok else out.strip().splitlines()[-1] if out.strip() else "failed"
    log(("PASS " if ok else "FAIL ") + f"({words} bitstream words)", "SYNTH")
    return Result("Synthesize (pyclbsynthesizer)", ok,
                  f"{words} words, mux 7'd{mux}",
                  [Check("backend synthesis -> bitstream", ok, detail)]), words


def connect_saleae(automation_port, device_id):
    from saleae import automation
    manager = automation.Manager.connect(port=automation_port)
    if device_id is None:
        devs = manager.get_devices()
        if not devs:
            manager.close()
            raise RuntimeError("no Saleae device found")
        device_id = devs[0].device_id
        dtype = str(devs[0].device_type)
    else:
        dtype = "(specified)"
    return manager, device_id, dtype


def main():
    ap = argparse.ArgumentParser(description="Hardware-in-the-loop driver for CLB designs")
    ap.add_argument("--port", default=project_config.flasher_port())
    ap.add_argument("--host", default="cont", help="synthesis backend (cont|local|prod|host:port)")
    ap.add_argument("--mux", type=int, default=None, help="force one input-mux code (no search)")
    ap.add_argument("--candidates", default=None, help="comma-separated mux codes to search")
    ap.add_argument("--freq", type=int, default=hbtest.DEFAULT_FREQ, help="PWM input frequency (Hz)")
    ap.add_argument("--sample-rate", type=int, default=hbtest.DEFAULT_RATE)
    ap.add_argument("--automation-port", type=int, default=10430)
    ap.add_argument("--device-id", default=None)
    ap.add_argument("--csv-dir", default=os.path.join(ROOT, "clb_hb_csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "clb_hil_report.html"))
    ap.add_argument("--skip-build", action="store_true",
                    help="skip synth/build/flash; test the firmware already on the target")
    ap.add_argument("--quiet-cli", action="store_true")
    args = ap.parse_args()

    if args.mux is not None:
        candidates = [args.mux]
    elif args.candidates:
        candidates = [int(x) for x in args.candidates.split(",")]
    else:
        candidates = SEARCH_CANDIDATES

    global _LOG_FH
    _LOG_FH = open(LOG_PATH, "w", encoding="utf-8")
    log(f"HIL run start. Task: {TASK}")
    log(f"candidates (IN0 mux) to try: {candidates}; watch live with: tail -f {LOG_PATH}")

    meta = {"Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Device": "PIC16F13145", "Port": args.port,
            "PWM input": f"{args.freq} Hz", "Task": TASK}

    iter_suite = Suite("Hardware-in-the-loop iterations",
                       "Each row: synthesize a candidate input-mux code -> build -> flash -> "
                       "check on the Saleae whether the half-bridge output follows the PWM "
                       "input. The loop stops at the first code that works.")
    hb_suite = None
    manager = None
    winning_mux = None

    try:
        manager, device_id, dtype = connect_saleae(args.automation_port, args.device_id)
        meta["Logic analyzer"] = dtype
        from smoketest import Console

        if args.skip_build:
            # test whatever is already flashed (single pass, no synth/build/flash)
            console = Console(args.port, echo=not args.quiet_cli)
            try:
                hb_suite = hbtest.run_suite(console, manager, device_id,
                                            args.sample_rate, args.csv_dir, freq=args.freq)
            finally:
                console.cmd("clb off"); console.close()
        else:
            for i, mux in enumerate(candidates, 1):
                log(f"===== iteration {i}/{len(candidates)}: IN0 mux = 7'd{mux} =====")
                checks = []
                synth_r, words = run_synth(mux, args.host)
                checks.append(synth_r.checks[0])
                build_ok = flash_ok = False
                input_ok = False; meas_freq = 0.0
                if synth_r.passed:
                    log("build (build.bat / XC8) ...", "BUILD")
                    br = run_build(); checks.append(Check("build (XC8)", br.passed, br.summary))
                    build_ok = br.passed
                    log(("PASS " if build_ok else "FAIL ") + br.summary, "BUILD")
                if build_ok:
                    log("flash (flash.py / MPLAB MDB) ...", "FLASH")
                    fr = run_flash(); checks.append(Check("flash (MDB)", fr.passed, fr.summary))
                    flash_ok = fr.passed
                    log("PASS programmed" if flash_ok else "FAIL", "FLASH")
                if flash_ok:
                    log("test on Saleae: does the half-bridge output follow PWM? ...", "TEST")
                    console = Console(args.port, echo=not args.quiet_cli)
                    try:
                        for ln in console.cmd("version").splitlines():
                            if "firmware | build" in ln:
                                meta["Firmware"] = ln.strip()
                        input_ok, meas_freq = hbtest.probe_input(
                            console, manager, device_id, args.sample_rate,
                            os.path.join(args.csv_dir, f"probe_mux{mux}"), args.freq)
                        checks.append(Check("half-bridge output follows PWM input", input_ok,
                                            f"HS measured {meas_freq:.0f} Hz vs PWM {args.freq} Hz"))
                        log(("PASS " if input_ok else "FAIL ")
                            + f"HS {meas_freq:.0f} Hz vs PWM {args.freq} Hz", "TEST")
                        if input_ok:
                            winning_mux = mux
                            log(f"input mux 7'd{mux} works -> running full half-bridge suite", "TEST")
                            hb_suite = hbtest.run_suite(console, manager, device_id,
                                                        args.sample_rate, args.csv_dir, freq=args.freq)
                    finally:
                        console.cmd("clb off"); console.close()

                iter_suite.add(Result(
                    f"iteration {i}: IN0 mux = 7'd{mux}", input_ok,
                    (f"works - PWM followed at {meas_freq:.0f} Hz" if input_ok
                     else "did not route PWM into the CLB"),
                    checks,
                    ["stage", "result", "detail"],
                    [["synth", "PASS" if synth_r.passed else "FAIL", f"{words} words"],
                     ["build", "PASS" if build_ok else ("FAIL" if synth_r.passed else "-"), ""],
                     ["flash", "PASS" if flash_ok else ("FAIL" if build_ok else "-"), ""],
                     ["input-follows-PWM", "PASS" if input_ok else "FAIL",
                      f"{meas_freq:.0f} Hz"]]))
                if input_ok:
                    break
    finally:
        if manager is not None:
            manager.close()

    if winning_mux is not None:
        meta["Input mux (found)"] = f"7'd{winning_mux}"

    suites = [iter_suite] if not args.skip_build else []
    if hb_suite is not None:
        suites.append(hb_suite)
    if not suites:
        suites = [iter_suite]

    overall = write_html(args.out, "CLB Half-Bridge - Hardware-in-the-Loop", meta, suites)
    log("=" * 56)
    for s in suites:
        log(f"  [{'PASS' if s.passed else 'FAIL'}] {s.name}")
    if winning_mux is not None:
        log(f"  input mux found: 7'd{winning_mux}")
    log(f"  report written: {args.out}")
    log(f"  OVERALL: {'PASS' if overall else 'FAIL'}")
    if _LOG_FH:
        _LOG_FH.close()
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
