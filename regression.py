#!/usr/bin/env python3
"""
regression.py
-------------
Serial-only regression tests for the Loop firmware console (no logic analyzer):

  * RX stress      - stream many commands back-to-back; every one must be
                     processed (guards the redraw/RX-overrun bug).
  * Input validation - out-of-range frequency, duty clamping, invalid input,
                     unknown commands all produce the right reply.
  * Reset          - `reset` reboots the device (banner reappears) and clears
                     state back to defaults.
  * Line editor    - mid-line insert, backspace and history recall via ANSI keys.

Run standalone (writes regression_report.html) or import `run(console)`.

Usage:
  python regression.py                 :: run on COM12, write regression_report.html
  python regression.py --port COM7
"""
import argparse
import os
import re
import sys
import time

from smoketest import Console
from testreport import Suite, Result, Check, write_html
import project_config

ESC, LB = 0x1B, 0x5B
K_UP, K_DOWN = [ESC, LB, 0x41], [ESC, LB, 0x42]
K_RIGHT, K_LEFT = [ESC, LB, 0x43], [ESC, LB, 0x44]


def _read(s, wait=0.4):
    time.sleep(wait)
    d = s.read(s.in_waiting or 1)
    time.sleep(0.06)
    if s.in_waiting:
        d += s.read(s.in_waiting)
    return d.decode("ascii", "ignore")


def _raw(s, data, wait=0.2):
    s.write(bytes(data))
    time.sleep(wait)


def _flush_line(console):
    """Submit any half-typed line in the firmware and drain the host buffer."""
    console.s.write(b"\r")
    time.sleep(0.2)
    console.s.reset_input_buffer()


def _cmd_expect(s, line, token, timeout=0.4):
    """Send a command and read until *token* appears (no fixed delay).
    Stale bytes are discarded first so we never match a previous reply."""
    s.reset_input_buffer()
    s.write((line + "\r").encode())
    out = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        n = s.in_waiting
        if n:
            out += s.read(n).decode("ascii", "ignore")
            if token in out:
                return True
        else:
            time.sleep(0.003)
    return token in out


# ----------------------------------------------------------------------
def test_input_validation(console) -> Result:
    cases = [
        ("pulse freq 100",     "range",            "frequency 100 Hz rejected (< 244)"),
        ("pulse freq 9000000", "range",            "frequency 9 MHz rejected (> 4 MHz)"),
        ("pulse freq 1000",    "Frequency ->",     "valid frequency accepted"),
        ("pulse a duty 150",   "100.000",          "duty 150 % clamped to 100 %"),
        ("pulse a duty -5",    "invalid",          "negative duty rejected"),
        ("pulse a duty abc",   "invalid",          "non-numeric duty rejected"),
        ("foobar",             "Unknown command",  "unknown command reported"),
        ("pulse wat",          "pulse freq",       "bad subcommand -> usage hint"),
    ]
    checks = []
    for cmd, expect, name in cases:
        resp = console.cmd(cmd)
        ok = expect.lower() in resp.lower()
        checks.append(Check(name, ok, "" if ok else f"sent '{cmd}', missing '{expect}'"))
    passed = all(c.passed for c in checks)
    return Result("Input validation & boundaries", passed,
                  f"{sum(c.passed for c in checks)}/{len(checks)} replies correct", checks)


def test_rx_stress(console) -> Result:
    # Stream commands as fast as the device acknowledges them (each whole command
    # is written in one shot, then we read to the prompt with no fixed delay).
    # This drives maximum throughput and guards the redraw/RX-overrun regression:
    # a dropped character means a command is never echoed back as 'requested N'.
    _flush_line(console)
    values = list(range(11, 41))                  # 30 distinct duty values
    found = []
    t0 = time.time()
    for v in values:
        if _cmd_expect(console.s, f"pulse a duty {v}", f"requested {v})"):
            found.append(v)
    dt = time.time() - t0
    missing = [v for v in values if v not in found]
    ok = not missing
    rate = len(values) / dt if dt else 0
    checks = [Check(f"{len(found)}/{len(values)} rapid commands acknowledged", ok,
                    "" if ok else f"missing replies for {missing}")]
    return Result("RX stress (rapid command streaming)", ok,
                  f"{len(values)} commands at ~{rate:.0f} cmd/s, all parsed without loss",
                  checks)


def test_reset(console) -> Result:
    checks = []
    console.cmd("pulse a on")                       # dirty the state
    console.cmd("pulse freq 5000")
    console.s.reset_input_buffer()
    console.s.write(b"reset\r")
    boot = _read(console.s, wait=0.8)               # wait for reboot + banner
    rebooted = "firmware | build" in boot
    checks.append(Check("device rebooted (banner reappeared)", rebooted,
                        "" if rebooted else "no banner after reset"))
    st = console.cmd("pulse status")
    a_off = bool(re.search(r"A \(RC0\):\s*OFF", st))
    deflt = "1000.000 Hz" in st
    checks.append(Check("channel A back OFF after reset", a_off))
    checks.append(Check("frequency back to 1000 Hz default", deflt))
    passed = all(c.passed for c in checks)
    return Result("Reset / power-on defaults", passed,
                  "reset reboots and restores defaults", checks)


def test_line_editor(console) -> Result:
    s = console.s
    checks = []
    _flush_line(console)                            # start from a clean line

    # mid-line insert: 'ac' + Left + 'b' -> 'abc'
    s.reset_input_buffer()
    _raw(s, b"ac"); _raw(s, K_LEFT); _raw(s, b"b"); _raw(s, b"\r")
    r1 = _read(s)
    c1 = "'abc'" in r1
    checks.append(Check("mid-line insert (ac <Left> b -> abc)", c1,
                        "" if c1 else "did not resolve to 'abc'"))

    # mid-line backspace: 'abc' + Left + Backspace -> 'ac'
    s.reset_input_buffer()
    _raw(s, b"abc"); _raw(s, K_LEFT); _raw(s, [0x7F]); _raw(s, b"\r")
    r2 = _read(s)
    c2 = "'ac'" in r2
    checks.append(Check("mid-line backspace (abc <Left> <BS> -> ac)", c2,
                        "" if c2 else "did not resolve to 'ac'"))

    # history: Up twice recalls a previous command and runs it
    s.reset_input_buffer()
    _raw(s, K_UP); _raw(s, K_UP); _raw(s, b"\r")
    r3 = _read(s)
    c3 = ("'abc'" in r3) or ("'ac'" in r3)
    checks.append(Check("history recall (Up Up Enter re-runs a past command)", c3,
                        "" if c3 else "no recalled command executed"))

    passed = all(c.passed for c in checks)
    return Result("Line editor & history", passed,
                  "cursor edit + Backspace + Up/Down history", checks)


def run(console) -> Suite:
    suite = Suite("Regression (serial)",
                  "Console behaviour verified over the serial port only.")
    suite.add(test_input_validation(console))
    suite.add(test_line_editor(console))
    suite.add(test_rx_stress(console))
    suite.add(test_reset(console))            # last: it reboots the device
    return suite


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Serial-only firmware regression tests")
    ap.add_argument("--port", default=project_config.flasher_port())
    ap.add_argument("--out", default=os.path.join(here, "regression_report.html"))
    args = ap.parse_args()

    console = Console(args.port, echo=False)
    try:
        suite = run(console)
    finally:
        console.close()

    for r in suite.results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.name} — {r.summary}")
        for c in r.checks:
            print(f"    [{'PASS' if c.passed else 'FAIL'}] {c.name}"
                  + (f"  ({c.detail})" if c.detail else ""))

    from datetime import datetime
    meta = {"Port": args.port, "Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    overall = write_html(args.out, "Loop firmware — serial regression", meta, [suite])
    print(f"\nWrote {args.out}  ->  {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
