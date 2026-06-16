#!/usr/bin/env python3
"""Capture the half-bridge at high resolution and dump the real state durations,
so we can see the actual dead-time and fix the analyser."""
import sys, traceback, statistics
import project_config
from smoketest import Console, saleae_capture
from clb_halfbridge_test import _read_states

def main():
    freq = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    dt   = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    rate = 100_000_000
    c = Console(project_config.flasher_port(), echo=False)
    try:
        c.cmd(f"pulse freq {freq}"); c.cmd("pulse a duty 50")
        c.cmd(f"clb dt {dt}"); print("clb on:", c.cmd("clb on").strip()[:50], flush=True)
        from saleae import automation
        m = automation.Manager.connect(port=10430)
        try:
            dev = m.get_devices()[0].device_id
            print(f"capture 100MS/s 0.005s freq={freq} dt={dt}", flush=True)
            csv = saleae_capture(m, [0, 1], rate, 0.005, "c:/work/Loop/clb_debug_csv", dev)
        finally:
            m.close()
        st = _read_states(csv)
        # classify each interval by (hs,ls) state and collect durations (ns)
        cats = {"both_low": [], "hs_only": [], "ls_only": [], "both_high": []}
        for (t0,h,l),(t1,_,_) in zip(st, st[1:]):
            d = (t1-t0)*1e9
            key = ("both_high" if h and l else "hs_only" if h else "ls_only" if l else "both_low")
            cats[key].append(d)
        total = (st[-1][0]-st[0][0])*1e9 if len(st)>1 else 0
        print(f"transitions={len(st)} total={total/1000:.1f}us", flush=True)
        for k,v in cats.items():
            if v:
                print(f"  {k:9s}: n={len(v):4d} sum={sum(v)/1000:8.2f}us "
                      f"median={statistics.median(v):8.1f}ns max={max(v):8.1f}ns", flush=True)
            else:
                print(f"  {k:9s}: none", flush=True)
        c.cmd("clb off")
    except Exception:
        traceback.print_exc()
    finally:
        c.close(); print("done", flush=True)

if __name__ == "__main__":
    main()
