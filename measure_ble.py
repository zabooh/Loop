#!/usr/bin/env python3
"""One-shot BLE_clk probe: clk-probe bitstream outputs cnt[2]=BLE/8 on RC0 and
cnt[8]=BLE/512 on RC1. Measure both, report BLE_clk. Robust prints + errors."""
import sys, traceback
import project_config
from smoketest import Console, saleae_capture, analyze_digital_csv

def main():
    print("[ble] open console", flush=True)
    c = Console(project_config.flasher_port(), echo=False)
    try:
        print("[ble] clb on:", c.cmd("clb on").strip()[:60], flush=True)
        print("[ble] connect saleae", flush=True)
        from saleae import automation
        m = automation.Manager.connect(port=10430)
        try:
            dev = m.get_devices()[0].device_id
            print(f"[ble] capture ch0,1 @ 25MS/s 0.01s (dev {dev})", flush=True)
            csv = saleae_capture(m, [1], 10_000_000, 0.05,
                                 "c:/work/Loop/clb_debug_csv", dev)
            print(f"[ble] captured: {csv}", flush=True)
        finally:
            m.close()
        # RC1 = cnt[8]: output period = 2^9 = 512 BLE_clk cycles -> BLE = freq*512
        mm = analyze_digital_csv(csv, 1)
        f = mm["freq_hz"]
        print(f"[ble] RC1=cnt[8] freq={f:.1f} Hz ({mm['cycles']} cyc) "
              f"-> BLE_clk = {f*512/1e6:.3f} MHz", flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        c.close()
        print("[ble] done", flush=True)

if __name__ == "__main__":
    main()
