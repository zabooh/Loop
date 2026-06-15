# CLB half-bridge with runtime dead-time

Logic for driving **RC0 = high-side** and **RC1 = low-side** as a complementary
half-bridge with a **dead-time that is adjustable at run time from the CLI**,
using the Configurable Logic Block (the PIC16F13145 has no CWG).

- [`clb_halfbridge.v`](clb_halfbridge.v) — the design (CLB Synthesizer form).
  One PWM input → HS/LS with a non-overlapping dead-time taken from `CLBSWIN`,
  so the CPU/CLI sets it live.
- [`clb_halfbridge.xdc`](clb_halfbridge.xdc) — maps the top-module ports to the
  CLB routing-fabric pins.
- [`synth.py`](synth.py) — headless Verilog → bitstream, **no GUI, no manual step**.

## Can this PC turn the Verilog into a bitstream? — Yes, fully headless

The CLB toolchain *is* scriptable. Microchip ships a command-line frontend,
**`pyclbsynthesizer`**, that sends the Verilog + `.xdc` to the CLB backend
(Yosys synthesis + VPR place-and-route + bitstream packing) and returns the
bitstream. There is no GUI and no MCC step in the loop.

```cmd
:: one-time install
pip install -i https://artifacts.microchip.com/artifactory/api/pypi/pypi/simple pyclbsynthesizer

:: synthesize clb_halfbridge.v + .xdc  ->  ../clbBitstream.S
python clb\synth.py
```

`synth.py` wraps `python -m pyclbsynthesizer synthesize -d 131 clb -o ... -b`
(`-d 131` is the alias for pic16f13145), copies the generated `bitstream.S`
into the project as `clbBitstream.S`, and prints the word count (102 words for
this design). The generated `psect clb_config,...,class=STRCODE,delta=2` and the
`start_clb_config` symbol match the bare-metal NVM-scanner loader already in
`main.c`, so the output drops straight in.

### Backend options

| `--host` | URL | Notes |
|----------|-----|-------|
| `cont` (default) | `http://dev.logic.microchip.com/continuous` | internal integration server; reachable on the Microchip network (verified) |
| `prod` | `https://logic.microchip.com` | public server; may be blocked from CI shells |
| `local` | `http://localhost:8001` | **fully offline / autonomous** — run the backend in Docker (below) |

Fully offline (no cloud at all):

```cmd
docker run --rm -p 8001:8001 artifacts.microchip.com:7999/microchip/logic/clb-backend:25.3.1
python clb\synth.py --host local
```

`python clb\synth.py --check` verifies backend reachability without synthesizing.

## CLB Synthesizer pin model (pic16f13145)

The "pins" in the backend routing model are **not** the data-sheet pin names.
Verified valid names for this family:

| Role | Synthesizer pin | In this design |
|------|-----------------|----------------|
| Clock (global BLE_clk) | port **`CLK`**, *left unmapped* in the `.xdc` | `always @(posedge CLK)` |
| Muxed inputs | `IN0`..`INn` + `(* pincfg.INx.mux = 7'd<code> *)` | `pwm_in` ← `IN0` |
| Software inputs | `CLBSWIN0`..`CLBSWINn` | `dt[2:0]` ← `CLBSWIN0..2` |
| External outputs | `PPS_OUT0`..`PPS_OUT7` → `CLBPPSOUT[n]` → pin via PPS | `hs`→`PPS_OUT0`→RC0, `ls`→`PPS_OUT1`→RC1 |
| Interrupts | `CLB_IRQ0`, `CLB_IRQ1` | (unused) |

Input/clock options are set with Verilog attributes, e.g.
`(* pincfg.IN0.syncmode.sync *)` and `(* pincfg.IN0.mux = 7'd<code> *)`.

The CLB clock source/divider is chosen at run time via the `CLBCLK` register
(the generated `clb1.c` uses `CLBCLK = 0x6` = HFINTOSC → 8 MHz BLE_clk).

## Runtime control from the CLI

The dead-time is `dt` cycles, written to `CLBSWIN` live — no re-synthesis needed:

```
clb on              enable the CLB half-bridge outputs
clb off             disable -> both pins low
clb dt <0..7>       set the dead-time in BLE_clk cycles (8 MHz -> 125 ns/step)
clb status          show enable state + current dead-time (cycles and ns)
```

```c
// dt = dead-time in BLE_clk cycles, 0..7  (CLBSWIN0..2)
void clb_set_deadtime(uint8_t dt) {
    CLBSWINL = (CLBSWINL & 0xF8) | (dt & 0x07);   // write CLBSWINL triggers the load
}
```

## How the dead-time logic works

A counter is cleared on every edge of `pwm_in` and counts up to `dt`, then holds.
`settled` is high only after `dt` cycles without an edge, so during each transition
both outputs stay low for `dt` cycles — that gap is the dead-time. After it,
`hs = pwm_in & settled` / `ls = ~pwm_in & settled` drive the complementary pair.

### Why 3-bit dead-time (0..7), not 4-bit

A 4-bit counter + 4-bit comparator **plus the two PPS outputs** overruns the CLB
place-and-route fabric — the backend fails with *"clock signal could not be
routed"*. The 3-bit design routes cleanly (full 102-word bitstream). For a longer
dead-time, **slow BLE_clk with the CLB clock divider** rather than widening the
counter (trade resolution for range).

## Why CLBSWIN (and not a fixed dead-time)

A fixed dead-time would be baked into the bitstream and could only be changed by
re-synthesising or by pre-building several bitstreams and switching them at run
time. Taking `dt` from `CLBSWIN` makes it **continuously adjustable from the CLI**
with a single bitstream — the recommended route for this use case.

## Status / next steps

- ✅ Headless synthesis verified: `synth.py` produces a 102-word `clbBitstream.S`.
- ⚠️ `pincfg.IN0.mux` in `clb_halfbridge.v` is a placeholder (`7'd0`). Set it
  to the PWM source's CLB-input code (data-sheet "CLB Module Inputs" table), or
  route the PWM out to a pin read via `CLBIN0PPS`. The Saleae test catches a wrong
  code immediately.
- ⏳ Wire `clbBitstream.S` + the `clb` CLI (`on/off/dt/status`) into `main.c` and add
  a Saleae half-bridge test (non-overlap + dead-time in BLE_clk cycles; sweep `dt`),
  then close the autonomous loop: `synth.py` → `build.bat` → `flash.py` → Saleae.
