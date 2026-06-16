#!/usr/bin/env python3
"""
pinid_test.py - verify the Saleae probe wiring RC0->D0 .. RC3->D3.

Triggers the firmware `pinid` command (which blinks RC0 1x, RC1 2x, RC2 3x,
RC3 4x per frame, 10 frames, ~2.3 s) while capturing all four channels, then
counts rising edges per channel. Correct wiring => channel Dn shows ~(n+1)
pulses per frame, i.e. the counts come out in the ratio 1 : 2 : 3 : 4.
"""
import csv
import os
import sys
import time

import project_config
from smoketest import Console, saleae_capture

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pinid_csv")
CHANNELS = [0, 1, 2, 3]
SAMPLE_RATE = 1_000_000         # min allowed; 5 ms pulse -> 5000 samples, ample
DURATION = 2.6                  # covers the ~2.3 s pinid burst
FRAMES = 10                     # must match cmd_pinid() in main.c


def count_rising(path, channel):
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
            raise ValueError(f"channel {channel} not in header {header}")
        rises, prev = 0, None
        for row in reader:
            if not row or len(row) <= max(tcol, ccol):
                continue
            try:
                v = int(float(row[ccol]))
            except ValueError:
                continue
            if prev is not None and prev == 0 and v == 1:
                rises += 1
            prev = v
    return rises


def main():
    port = project_config.flasher_port()
    print(f"[pinid] opening console on {port}")
    console = Console(port, echo=False)
    try:
        from saleae import automation
        print(f"[pinid] connecting Saleae, capturing ch {CHANNELS} @ "
              f"{SAMPLE_RATE/1e6:.1f} MS/s for {DURATION:.1f} s")
        manager = automation.Manager.connect(port=10430)
        try:
            devs = manager.get_devices()
            if not devs:
                print("ERROR: no Saleae device"); return 1
            device_id = devs[0].device_id
            # fire pinid WITHOUT waiting for the reply (it blocks ~2.3 s on-chip),
            # then start the capture right away so the burst lands inside it.
            console.s.reset_input_buffer()
            console.s.write(b"pinid\r")
            time.sleep(0.15)
            csv_path = saleae_capture(manager, CHANNELS, SAMPLE_RATE, DURATION,
                                      OUT, device_id)
        finally:
            manager.close()
    finally:
        console.close()

    names = {0: "RC0", 1: "RC1", 2: "RC2", 3: "RC3"}
    print(f"\n[pinid] rising-edge count per channel ({csv_path}):")
    counts = {ch: count_rising(csv_path, ch) for ch in CHANNELS}
    # The Saleae arms ~1 s after the burst starts, so we never see all FRAMES.
    # Judge by RATIO instead: counts[ch] / (ch+1) must be ~equal across channels
    # (= the number of frames actually captured), i.e. the pattern is 1:2:3:4.
    norm = {ch: counts[ch] / (ch + 1) for ch in CHANNELS}
    frames_seen = sum(norm.values()) / len(norm)
    monotonic = all(counts[c] < counts[c + 1] for c in CHANNELS[:-1])
    spread_ok = all(abs(norm[ch] - frames_seen) <= 0.30 * frames_seen for ch in CHANNELS)
    ok = monotonic and spread_ok and counts[0] > 0
    for ch in CHANNELS:
        print(f"   D{ch}: {counts[ch]:3d} rises  (/{ch+1} = {norm[ch]:.1f} frames; "
              f"expect {names[ch]} -> {ch+1} pulses/frame)")
    print(f"\n[pinid] pattern 1:2:3:4  monotonic={monotonic}  "
          f"ratio-consistent={spread_ok}  (~{frames_seen:.1f} frames captured)")
    print(f"[pinid] WIRING {'OK: RC0->D0, RC1->D1, RC2->D2, RC3->D3' if ok else 'MISMATCH - check probes'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
