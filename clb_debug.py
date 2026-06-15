#!/usr/bin/env python3
"""
clb_debug.py - interactive hardware debug helper for the CLB / PWM signals.

Drives the serial console with arbitrary commands, then captures one or more
Saleae channels and reports the frequency / duty / idle level of each. This is
the manual counterpart to clb_hil.py: use it to localise a problem ("does plain
PWM work?", "does `clb on` change RC0 at all?", "is PWM1 reaching the CLB?").

Wiring on this bench:
    RC0 -> Saleae ch0      RC2 -> Saleae ch2
    RC1 -> Saleae ch1      RC3 -> Saleae ch3
(RC0/RC1 are the half-bridge HS/LS outputs; RC2/RC3 are spare probe pins that a
debug build can route internal signals to via PPS, e.g. RC2PPS=0x2C for PWM1.)

Examples:
  # plain PWM sanity: RC0=PWM1, RC1=PWM2 should both show 10 kHz
  python clb_debug.py --cmds "pulse freq 10000;pulse a duty 50;pulse a on;pulse b on" --channels 0,1

  # CLB half-bridge: what do RC0/RC1 do when the CLB is enabled?
  python clb_debug.py --cmds "pulse freq 10000;pulse a duty 50;clb dt 3;clb on" --channels 0,1,2,3

  # just run commands and print the console replies (no capture)
  python clb_debug.py --cmds "clb status;pulse status" --no-capture
"""
import argparse
import os
import sys

import project_config
from smoketest import Console, saleae_capture, analyze_digital_csv


def main():
    ap = argparse.ArgumentParser(description="CLI + Saleae debug helper for CLB/PWM")
    ap.add_argument("--cmds", default="", help="';'-separated console commands to send first")
    ap.add_argument("--channels", default="0,1,2,3", help="Saleae channels to capture")
    ap.add_argument("--freq", type=int, default=10000, help="expected frequency (for duration)")
    ap.add_argument("--sample-rate", type=int, default=50_000_000)
    ap.add_argument("--seconds", type=float, default=None, help="capture duration (default ~60 periods)")
    ap.add_argument("--no-capture", action="store_true", help="only run commands, print replies")
    ap.add_argument("--port", default=project_config.flasher_port())
    ap.add_argument("--automation-port", type=int, default=10430)
    ap.add_argument("--device-id", default=None)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "clb_debug_csv"))
    args = ap.parse_args()

    channels = [int(c) for c in args.channels.split(",") if c.strip() != ""]
    duration = args.seconds if args.seconds else max(0.01, 60.0 / args.freq)

    print(f"[debug] opening console on {args.port}")
    console = Console(args.port, echo=True)
    try:
        for c in [x.strip() for x in args.cmds.split(";") if x.strip()]:
            console.cmd(c)
        if args.no_capture:
            return 0

        from saleae import automation
        print(f"[debug] connecting Saleae, capturing ch {channels} @ {args.sample_rate/1e6:.0f} MS/s "
              f"for {duration*1e3:.0f} ms")
        manager = automation.Manager.connect(port=args.automation_port)
        try:
            device_id = args.device_id
            if device_id is None:
                devs = manager.get_devices()
                if not devs:
                    print("ERROR: no Saleae device"); return 1
                device_id = devs[0].device_id
            csv_path = saleae_capture(manager, channels, args.sample_rate, duration,
                                      args.out, device_id)
        finally:
            manager.close()

        print(f"\n[debug] per-channel measurement ({csv_path}):")
        names = {0: "RC0", 1: "RC1", 2: "RC2", 3: "RC3"}
        for ch in channels:
            m = analyze_digital_csv(csv_path, ch)
            print(f"   ch{ch} ({names.get(ch,'?')}): {m['freq_hz']:.1f} Hz, "
                  f"duty {m['duty_pct']:.2f} %, {m['cycles']} cycles, idle level {m['level']}")
    finally:
        console.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
