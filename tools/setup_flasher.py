#!/usr/bin/env python3
"""
setup_flasher.py — detect the PIC16F13145 Curiosity Nano and record its serial
console port (and debugger serial) in setup_flasher.config.

The Python test tools (smoketest.py, regression.py, freq_sweep.py, duty_sweep.py,
run_ci.py) read this file for their default `--port`, so after cloning you run
this once and everything finds the board automatically. Flashing itself
(flash.py / MPLAB MDB) auto-detects the on-board `pkobnano` debugger; the stored
serial is informational and can be passed as `flash.py --serial` if several
boards are connected.

Usage:
  python setup_flasher.py            # interactive
  python setup_flasher.py --auto     # accept the single detected board
"""
import argparse
import json
import os
import sys

import serial.tools.list_ports

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(_HERE, "setup_flasher.config")


def _is_curiosity_nano(p):
    """Heuristic: detect a Curiosity Nano virtual COM port / nEDBG debugger."""
    if p.description and "curiosity virtual com" in p.description.lower():
        return True
    if p.serial_number and p.serial_number.upper().startswith("MC"):
        return True
    if p.vid in (0x04D8, 0x03EB):                 # Microchip / Atmel-Microchip
        return True
    if p.manufacturer and "microchip" in p.manufacturer.lower():
        return True
    return False


def _com_num(p):
    s = "".join(c for c in p.device if c.isdigit())
    return int(s) if s else 9999


def _print_port(label, p):
    vid = hex(p.vid) if p.vid is not None else "N/A"
    pid = hex(p.pid) if p.pid is not None else "N/A"
    print(f"  {label}:")
    print(f"    Device      : {p.device}")
    print(f"    Description : {p.description}")
    print(f"    Serial Nr.  : {p.serial_number or 'N/A'}")
    print(f"    Manufacturer: {p.manufacturer or 'N/A'}")
    print(f"    VID:PID     : {vid}:{pid}")


def _select(ports):
    for i, p in enumerate(ports, 1):
        print(f"  [{i}] {p.device}  SN={p.serial_number or 'N/A'}  {p.description}")
    while True:
        try:
            raw = input(f"  Selection (1-{len(ports)}): ").strip()
        except (KeyboardInterrupt, EOFError):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(ports):
            return ports[int(raw) - 1]
        print("  Invalid input, please try again.")


def main():
    ap = argparse.ArgumentParser(description="Configure the Curiosity Nano COM port")
    ap.add_argument("--auto", action="store_true",
                    help="accept the single detected board without prompting")
    args = ap.parse_args()

    print("=" * 60)
    print("  setup_flasher.py — Curiosity Nano configuration")
    print("=" * 60)

    all_ports = sorted(serial.tools.list_ports.comports(), key=_com_num)
    matches = [p for p in all_ports if _is_curiosity_nano(p)]

    if not matches:
        print("\n[WARN] No Curiosity Nano detected by heuristics.")
        if not all_ports:
            print("[ERROR] No serial ports at all — connect the board via USB.")
            return 1
        print("Falling back to the full COM-port list:")
        matches = all_ports

    print(f"\nDetected {len(matches)} candidate port(s):\n")
    for i, p in enumerate(matches, 1):
        _print_port(f"#{i}", p)
        print()

    if len(matches) == 1 and (args.auto or True):
        chosen = matches[0]
        if not args.auto:
            try:
                ans = input(f"Use {chosen.device} (SN {chosen.serial_number})? [Y/n]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                return 0
            if ans in ("n", "no"):
                chosen = _select(matches)
    else:
        if args.auto:
            print("[auto] multiple candidates — using the first.")
            chosen = matches[0]
        else:
            print("Multiple candidates — please pick the Curiosity Nano:")
            chosen = _select(matches)

    if chosen is None:
        print("Aborted.")
        return 0

    config = {
        "com_port": chosen.device,
        "serial": chosen.serial_number or "",
        "description": chosen.description or "",
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

    print(f"\n[OK] Configuration saved: {CONFIG_FILE}")
    print(f"    COM Port  : {config['com_port']}")
    print(f"    Serial Nr.: {config['serial'] or 'N/A'}")
    print("\nDone. The test tools will now default to this port.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
