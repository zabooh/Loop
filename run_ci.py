#!/usr/bin/env python3
"""
run_ci.py
---------
One-command CI for the Loop project: build -> flash -> test -> HTML report.

  1. build.bat            (compile with XC8)
  2. flash.py             (program the target over the MPLAB MDB)
  3. regression.py        (serial-only: validation, RX stress, editor, reset)
  4. smoketest.py         (Saleae: frequency + duty on RC0/RC1, duty-hold)

All results are collected into a single self-contained HTML protocol
(`report.html`) with an overall PASS/FAIL verdict. Exit code is 0 only if
everything passed.

Usage:
  python run_ci.py                       :: full pipeline on COM12
  python run_ci.py --skip-build          :: use the existing binary
  python run_ci.py --skip-flash          :: test the firmware already on target
  python run_ci.py --sample-rate 25000000
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

import regression
import smoketest
from smoketest import Console
from testreport import Suite, Result, Check, write_html
import project_config

ROOT = os.path.dirname(os.path.abspath(__file__))


def run_build() -> Result:
    print("=== Build (build.bat) ===")
    p = subprocess.run(["cmd", "/c", os.path.join(ROOT, "build.bat")],
                       cwd=ROOT, capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    ok = (p.returncode == 0) and ("Build finished" in out)
    mem = [ln.strip() for ln in out.splitlines()
           if "space" in ln.lower() and "%" in ln]
    warns = [ln.strip() for ln in out.splitlines() if "warning" in ln.lower()]
    rows = [[m.split("used")[0].strip(), m.split("(")[-1].rstrip(")")] for m in mem] if mem else None
    checks = [Check("build.bat exit 0 and linked", ok,
                    "" if ok else f"exit {p.returncode}")]
    if warns:
        checks.append(Check("no compiler warnings", False, f"{len(warns)} warning(s)"))
    print(("  PASS" if ok else "  FAIL") + f" (exit {p.returncode})")
    return Result("Build (XC8 via build.bat)", ok and not warns,
                  "; ".join(mem) if mem else "compiled",
                  checks, ["Memory region", "used"] if rows else None, rows)


def run_flash() -> Result:
    print("=== Flash (flash.py / MPLAB MDB) ===")
    from flash import flash
    hex_path = os.path.join(ROOT, "out", "Loop", "default.hex")
    rc = flash(hex_path, label="CI")
    ok = (rc == 0)
    print("  PASS" if ok else "  FAIL")
    return Result("Flash (MPLAB MDB over ICSP)", ok,
                  f"programmed {os.path.relpath(hex_path, ROOT)}",
                  [Check("Program succeeded", ok)])


def main():
    ap = argparse.ArgumentParser(description="Build/flash/test CI with HTML report")
    ap.add_argument("--port", default=project_config.flasher_port())
    ap.add_argument("--sample-rate", type=int, default=10_000_000)
    ap.add_argument("--device-id", default=None)
    ap.add_argument("--automation-port", type=int, default=10430)
    ap.add_argument("--csv-dir", default=os.path.join(ROOT, "smoketest_csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "report.html"))
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-flash", action="store_true")
    args = ap.parse_args()

    suites = []
    meta = {"Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Port": args.port}

    # ---- 1+2: build & flash -------------------------------------------------
    bf = Suite("Build & flash", "Compile with XC8 and program the target over ICSP.")
    build_ok = True
    if not args.skip_build:
        r = run_build(); bf.add(r); build_ok = r.passed
    flash_ok = True
    if not args.skip_flash:
        if build_ok:
            r = run_flash(); bf.add(r); flash_ok = r.passed
        else:
            bf.add(Result("Flash (MPLAB MDB over ICSP)", False,
                          "skipped — build failed", []))
            flash_ok = False
    suites.append(bf)

    device_ready = build_ok and flash_ok
    reg_suite = Suite("Regression (serial)")
    smoke_suite = Suite("Smoke test (Saleae)")

    if not device_ready:
        reg_suite.skipped = smoke_suite.skipped = True
        reg_suite.skip_reason = smoke_suite.skip_reason = "build or flash failed"
        suites += [reg_suite, smoke_suite]
    else:
        console = Console(args.port, echo=False)
        try:
            ver = console.cmd("version")
            for ln in ver.splitlines():
                if "firmware | build" in ln:
                    meta["Firmware"] = ln.strip()

            # ---- 3: serial regression ----
            print("\n=== Regression (serial) ===")
            reg_suite = regression.run(console)

            # ---- 4: Saleae smoke test ----
            print("\n=== Smoke test (Saleae) ===")
            try:
                from saleae import automation
                manager = automation.Manager.connect(port=args.automation_port)
                try:
                    device_id = args.device_id
                    if device_id is None:
                        devs = manager.get_devices()
                        if not devs:
                            raise RuntimeError("no Saleae device found")
                        device_id = devs[0].device_id
                        meta["Logic analyzer"] = str(devs[0].device_type)
                    smoke_suite = smoketest.run_suite(
                        console, manager, device_id, args.sample_rate, args.csv_dir)
                finally:
                    manager.close()
            except Exception as e:
                smoke_suite.skipped = True
                smoke_suite.skip_reason = f"Saleae unavailable: {e}"
                print(f"  SKIP: {e}")
        finally:
            console.close()
        suites += [reg_suite, smoke_suite]

    # ---- report -------------------------------------------------------------
    images = [(cap, img) for cap, img in
              [("Frequency sweep", "freq_sweep.png"),
               ("Duty-cycle sweep", "duty_sweep.png")]
              if os.path.isfile(os.path.join(ROOT, img))]
    overall = write_html(args.out, "Loop firmware — CI report", meta, suites, images)

    print("\n" + "=" * 60)
    for s in suites:
        tag = "SKIP" if s.skipped else ("PASS" if s.passed else "FAIL")
        print(f"  [{tag}] {s.name}")
    print(f"  Report: {args.out}")
    print(f"  OVERALL: {'PASS' if overall else 'FAIL'}")
    print("=" * 60)
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
