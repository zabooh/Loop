# CLB half-bridge with runtime dead-time (design)

Logic for driving **RC0 = high-side** and **RC1 = low-side** as a complementary
half-bridge with a **dead-time that is adjustable at run time from the CLI**,
using the Configurable Logic Block (the PIC16F13145 has no CWG).

- [`clb_halfbridge.v`](clb_halfbridge.v) — the design. One PWM input → HS/LS with
  a non-overlapping dead-time taken from `CLBSWIN`, so the CPU/CLI sets it live.

## Can this PC turn the Verilog into a bitstream?

**Yes — via MCC, not from a shell.** The synthesizer is the MCC Melody component
**`@mchp-mcc/scf-pic8-clb-v1`** (present in the installed MCC 8-bit catalog). It
compiles Verilog → CLB bitstream **inside MCC's "Generate" step** (the MCC backend
`host.jar`, driven by the VS Code MCC extension or the MPLAB X MCC plugin). There
is **no standalone command-line synthesizer** on this machine, so the bitstream is
produced when *you* run Generate in MCC — it cannot be generated from a script.
The component downloads on first use (one-time network).

What is hand-authored here (the Verilog + the integration plan below) and what MCC
produces (the bitstream as `clb1.c/.h` + the CLB init/driver) are separate steps.

## Bringing it up in MCC Melody

1. New MCC Melody project for the PIC16F13145; add the **CLB** component
   (downloads `scf-pic8-clb-v1` the first time).
2. CLB Synthesizer → **Verilog** input → import `clb_halfbridge.v`, set as top.
3. **Clock:** set `CLBCLK` source + divider so `clk` (BLE_clk) is your base rate,
   e.g. HFINTOSC/4 = 8 MHz → 125 ns dead-time steps.
4. **Inputs:**
   - `pwm_in` ← the PWM1 output (routed internally into the CLB, not to a pin).
   - `dt[3:0]` ← four bits of the **CLBSWIN** software-input register.
5. **Outputs:** map `hs` → **RC0** and `ls` → **RC1** via the CLB PPS outputs.
6. Generate → the NVM scanner loads the netlist; set the CLB `EN` bit to run.

## Runtime control from the CLI

The dead-time is `dt` cycles, written to `CLBSWIN` live — no re-synthesis needed:

```
clb on              enable the CLB half-bridge outputs
clb off             disable -> both pins low
clb dt <0..15>      set the dead-time in BLE_clk cycles (e.g. 8 MHz -> 125 ns/step)
clb status          show enable state + current dead-time (cycles and ns)
```

The C side (after MCC generates the CLB driver) is roughly:

```c
// dt = dead-time in clk cycles, 0..15
void clb_set_deadtime(uint8_t dt) {
    CLBSWINL = (CLBSWINL & 0xF0) | (dt & 0x0F);   // 4 dt bits in CLBSWIN
}
```

(The exact register/field names come from the MCC-generated CLB driver.)

## How the dead-time logic works

A counter is cleared on every edge of `pwm_in` and counts up to `dt`, then holds.
`settled` is high only after `dt` cycles without an edge, so during each transition
both outputs stay low for `dt` cycles — that gap is the dead-time. After it,
`hs = pwm_in & settled` / `ls = ~pwm_in & settled` drive the complementary pair.

Resource estimate: ~10–15 of the 32 BLEs (1 edge flop + a 4-bit counter +
comparator + two output gates); the synthesizer reports the exact utilisation.

## Why CLBSWIN (and not a fixed dead-time)

The dead-time would otherwise be baked into the bitstream (a fixed shift-register
depth) and could only be changed by re-synthesising or by pre-building several
bitstreams and switching them at run time (the "Multiple CLB Configurations"
approach). Taking `dt` from `CLBSWIN` makes it **continuously adjustable from the
CLI** with a single bitstream — the recommended route for this use case.

## Status / caveats

- This is the **logic design + integration plan**, not a flashable image. The
  bitstream and CLB driver are produced by MCC Generate (see above), which is an
  IDE/backend step that cannot be run from this shell.
- The main `Loop` firmware is a hand-written bare-metal CMake project, not an MCC
  project. Integrating the CLB means adding the MCC-generated CLB files to the
  build and wiring `CLBSWIN`/enable to the `clb` CLI command — straightforward
  once the MCC output exists; ask and we'll do that wiring next.
