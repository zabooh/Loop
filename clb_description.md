# The Configurable Logic Block (CLB) on the PIC16F13145

A precise description of what the CLB is, what feeds into it, what it is built from,
what comes out of it, and how it is clocked. All facts are taken from the
PIC16F13145 data sheet, chapter 29 (*Configurable Logic Block*); section numbers
link to the online data sheet.

> **Scope:** applies to the **PIC16F131xx** family (PIC16F13145 used as the
> reference part). §1–§9 are device-generic (data-sheet facts); §10–§11 capture
> findings and a worked example specific to this repository.

> 🛑 **Before relying on §10, read this.** §1–§9 are data-sheet facts and are solid.
> §10–§11 are **empirical findings from one specific setup** — the headless
> `pyclbsynthesizer` Verilog flow, one silicon revision, automated verification via PPS
> outputs + a logic analyzer. In that setup many designs failed and only simple
> *registered counter* designs were robust. **These findings conflict in places with
> the data sheet and with official internal CLB examples** (which show working
> combinational/sequential/mixed logic, external inputs via `CLBINxPPS` — e.g. a
> quadrature decoder, input-synchronizer demos using `TMR0_OUT`, a 4-bit counter with
> enable + reset). So treat §10 as **"what worked in our flow", not "what the CLB can
> do"** — the failures are most likely **toolflow / mapping / setup** issues, not
> silicon limits, and there are **no CLB-specific points in the official errata**. When
> in doubt, start from an MCC / official reference design (§10.0).

---

## Table of contents

1. [What a CLB is](#1-what-a-clb-is)
2. [Inputs](#2-inputs)
   - [2.1 CLB input signals (pins and peripherals)](#21-clb-input-signals-pins-and-peripherals)
   - [2.2 Programmable edge detectors / input synchronizers](#22-programmable-edge-detectors--input-synchronizers)
   - [2.3 Software inputs — `CLBSWIN`](#23-software-inputs--clbswin)
   - [2.4 Internal feedback inputs](#24-internal-feedback-inputs)
3. [Elements the CLB is built from](#3-elements-the-clb-is-built-from)
   - [3.1 Basic Logic Elements (BLEs) — 32 of them](#31-basic-logic-elements-bles--32-of-them)
   - [3.2 Dedicated 3-bit hardware counter](#32-dedicated-3-bit-hardware-counter)
   - [3.3 Routing / Configuration latches](#33-routing--configuration-latches)
4. [Outputs](#4-outputs)
   - [4.1 Eight PPS outputs — `CLBPPSOUT[0..7]`](#41-eight-pps-outputs--clbppsout07)
   - [4.2 Internal peripheral connections](#42-internal-peripheral-connections)
   - [4.3 Interrupts — four of them](#43-interrupts--four-of-them)
5. [Clocking](#5-clocking)
   - [`CLBCLK` clock sources (Table 29-4)](#clbclk-clock-sources-table-29-4)
6. [Configuration & load sequence (summary)](#6-configuration--load-sequence-summary)
7. [How the bitstream is loaded (in detail)](#7-how-the-bitstream-is-loaded-in-detail)
   - [7.1 What "the bitstream" actually is](#71-what-the-bitstream-actually-is)
   - [7.2 The three actors](#72-the-three-actors)
   - [7.3 The load sequence, register by register](#73-the-load-sequence-register-by-register)
   - [7.4 Why the CRC must be enabled first (the `DABORT` trap)](#74-why-the-crc-must-be-enabled-first-the-dabort-trap)
   - [7.5 Scanner modes — why burst](#75-scanner-modes--why-burst)
   - [7.6 Where this sits in the overall flow](#76-where-this-sits-in-the-overall-flow)
8. [How to author a CLB design](#8-how-to-author-a-clb-design)
   - [8.1 Two ways to enter the logic](#81-two-ways-to-enter-the-logic)
   - [8.2 The synthesizer (back end)](#82-the-synthesizer-back-end)
   - [8.3 Verilog port & pin conventions](#83-verilog-port--pin-conventions)
   - [8.4 Writing synthesizable Verilog for the CLB](#84-writing-synthesizable-verilog-for-the-clb)
   - [8.5 Synthesizable building blocks (templates)](#85-synthesizable-building-blocks-templates)
9. [CLB vs CLC vs CWG — when to use which](#9-clb-vs-clc-vs-cwg--when-to-use-which)
10. [Empirical findings from our setup (NOT general CLB limits)](#10-empirical-findings-from-our-setup-not-general-clb-limits)
    - [10.0 How these findings were established (and the verification's limits)](#100-how-these-findings-were-established-and-the-verifications-limits)
    - [10.1 What worked / failed in our flow (setup-specific)](#101-what-worked--failed-in-our-flow-setup-specific)
    - [10.2 The two findings that bit us first (flow-specific)](#102-the-two-findings-that-bit-us-first-flow-specific)
    - [10.3 Place-and-route is fragile and non-monotonic](#103-place-and-route-is-fragile-and-non-monotonic)
    - [10.4 Load-time traps](#104-load-time-traps-recap-of-7--silent-failures)
    - [10.5 Toolchain / authoring gotchas](#105-toolchain--authoring-gotchas)
    - [10.6 The recipe that was reliable in our flow](#106-the-recipe-that-was-reliable-in-our-flow)
11. [Worked example: the half-bridge in this repo](#11-worked-example-the-half-bridge-in-this-repo)
12. [At a glance](#12-at-a-glance)
13. [Glossary](#13-glossary)

---

## 1. What a CLB is

The **Configurable Logic Block (CLB)** is a small, **FPGA-like programmable logic
fabric** integrated into the microcontroller. Instead of being a fixed-function
peripheral that you configure with a handful of registers (like the CLC, CWG or
NCO), the CLB is a generic array of look-up tables and flip-flops whose function and
interconnect are defined by a **configuration netlist**.

You do **not** program the CLB by writing to control registers directly. Instead:

1. The logic is entered through a **Configuration Interface** (a design tool, e.g.
   the MPLAB CLB synthesizer fed from Verilog), which produces a **netlist**.
2. The netlist is stored in **Program Flash Memory (PFM)**.
3. At run time the **NVM Scanner** (working with the CRC module) transfers the
   netlist from PFM into the CLB's configuration latches and LUTs.
4. Only after the scan completes is the module enabled via the `EN` bit in `CLBCON`.

See [§29.1 CLB Module Enable](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-B27FF7C2-7D66-4F7E-9F27-F649E578D610.html)
and [§29.8 CLB Configuration](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-F832DBF6-F9D2-4F5F-984D-2AA7CEE01416.html).

The CLB exists to implement custom, low-latency hardware logic and state machines
that run independently of the CPU — glue logic that would otherwise need an external
CPLD/FPGA or that no dedicated on-chip peripheral provides.

---

## 2. Inputs

The CLB takes signals from three different sources, all selectable through the
Configuration Interface.

### 2.1 CLB input signals (pins and peripherals)
There are **16 CLB input selection latches**. Each selects one signal — either an
external pin (routed in through `CLBIN0PPS..CLBIN3PPS` / PPS) or an internal
peripheral output — to bring into the fabric. These 16 signals are the connection to
the rest of the chip.

### 2.2 Programmable edge detectors / input synchronizers
Each of the 16 selected inputs passes through a **programmable edge detector** before
entering the fabric (the **CLB Input Synchronizer latches** configure it):

- **Positive edge** triggered (default),
- **Negative edge** triggered (set Input Synchronizer[0] = `1`),
- or **bypassed** entirely (signal fed in asynchronously, no synchronization).

> If a BLE uses its output flop, take care that a *bypassed* (unsynchronized) input
> does not drive the flop into metastability.

See [§29.4.2 Programmable Edge Detectors](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-1DD48F82-613E-4247-8282-F6ACA6A20D9B.html).

### 2.3 Software inputs — `CLBSWIN`
User firmware can "bit-bang" values straight into the fabric through the 32-bit
**`CLBSWIN`** register, formed from four 8-bit registers
**`CLBSWINU : CLBSWINH : CLBSWINM : CLBSWINL`** (`CLBSWIN[31:0]`). Any of these 32
bits can be selected as a LUT input.

Write semantics (important):
- Write `CLBSWINU`, `CLBSWINH`, `CLBSWINM` **first**, then `CLBSWINL` **last**.
- Writing `CLBSWINL` latches all four bytes at once, sets the `BUSY` bit in `CLBCON`,
  and locks the registers for **one `BLE_clk` cycle** while they synchronize.

See [§29.4.1 CLB Software Input Register](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-6C18D8A9-B4D4-45C0-B2C7-3E317B94CECF.html).

> ✅ **`CLBSWIN` works — but you MUST do the `BUSY` handshake (verified, see §10.2).**
> To write it: wait `while(CLBCONbits.BUSY){}`, write **U, H, M, then L last**, then wait
> `while(CLBCONbits.BUSY){}` again. With this, a registered passthrough cleanly followed
> `CLBSWIN` on hardware (all-ones→high, zero→low, repeatable). Our earlier "CLBSWIN dead"
> was purely the **missing handshake** in firmware, not the silicon. **Mapping caveat:** the
> synthesizer maps each Verilog `CLBSWINk` to an *arbitrary* `CLBSWIN[31:0]` register bit
> (observed `CLBSWIN0`→bit 2), so for multi-bit values discover the per-design bit positions
> (§10.2). (Pin `INx` *data* inputs we still couldn't get working in our flow — that one
> remains open; a pin used as the **clock** works.)

### 2.4 Internal feedback inputs
Two on-chip-generated signal groups are also available as inputs to the BLEs:
- the **3-bit counter** outputs (§3.2), and
- the **BLE outputs themselves**, fed back as possible inputs (so logic can be
  cascaded across BLEs).

---

## 3. Elements the CLB is built from

### 3.1 Basic Logic Elements (BLEs) — 32 of them
The **BLE is the primary building block**; the CLB module contains **32 BLEs**. Each
BLE has two parts:

| Element | Description |
|---------|-------------|
| **Look-Up Table (LUT)** | A memory array with **4 input bits → 1 output bit**, i.e. **16 storage elements** (one per input combination). The 4 inputs act as the address selecting which stored bit is presented at the output. This implements any arbitrary 4-input combinational function. |
| **Output flop** | An optional flip-flop on the LUT output. The **BLE Flop Select** bit chooses whether the BLE output is the LUT result directly (combinational) or the registered/flopped version (sequential). |

The LUT itself has **no reset**. The output flop is reset by: setting the `CLBMD`
PMD bit, a device Reset, or clearing the `EN` bit. Unused LUTs should be configured
to all-`0` to minimize current.

![Figure 29-1. Basic Logic Element (BLE) Simplified Block Diagram](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-A1E67831-5A13-4C5E-A882-514A6D86B97A-low.png)

See [§29.2 Basic Logic Element (BLE)](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-3812C624-01AD-4C79-BEB7-39719F4A108B.html).

### 3.2 Dedicated 3-bit hardware counter
For state-machine designs the CLB provides one **dedicated 3-bit counter**:

- **Clocked by `BLE_clk`** (the output of the CLB clock divider, §5).
- **Counter Stop** and **Counter Reset** can each be driven by **any of the 32 BLE
  outputs** (configurable).
- Each of the 3 count bits is available as an input to the BLEs, selected via the
  **Counter[n] Output Selection latches**.

> **It operates as a one-hot ring counter.** The official CLB training describes this
> block as a *"3-bit straight ring counter (one-hot counter) — at any time one and only
> one output is high,"* useful for state machines / event counting. Its **8 decoded
> outputs** feed an array of multiplexers that present 8 signals to the BLEs (that mux
> selection is **common to all BLEs**). So it is not a general binary up-counter; for a
> binary count you synthesize a `reg [N:0]` from BLE flip-flops (next note).

> **Don't confuse the two kinds of counter.** This **dedicated hardware counter is only
> 3 bits** (and one-hot, above). The wider counters referenced in §10/§11 (`cnt[7]`, `cnt[8]`, `cnt[11]`, …)
> are **ordinary counters synthesized from BLE flip-flops**, *not* this dedicated block.
> A `reg [N:0]` in Verilog becomes BLE logic; the dedicated 3-bit counter is a distinct
> resource the tool may use for small counts.

![Figure 29-2. 3-Bit Counter Block Diagram](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-679A8372-99EC-4286-8B4B-1411D7BC4784-low.png)

See [§29.3 Dedicated 3-Bit Counter](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-96CCB459-A4E9-4B66-9CA2-631D094AA895.html).

### 3.3 Routing / Configuration latches
The interconnect is itself made of configuration latches, all written from the
netlist by the NVM scanner:
- **CLB Input Selection** latches (which 16 signals enter, §2.1),
- **CLB Input Synchronizer** latches (edge-detector mode, §2.2),
- **BLE Input Selection** latches (which signals feed each BLE's 4 LUT inputs),
- **CLB Look-Up Table** latches (the 16 bits of each LUT),
- **BLE Flop Select** latches (combinational vs. registered output),
- **Counter Stop / Reset / Output Selection** latches (§3.2),
- **CLB Output Selection** latches (which BLE drives each PPS output, §4.1),
- **CLB Interrupt Selection** latches (§4.3),
- **CLB Clock Divider** latches (§5).

---

## 4. Outputs

### 4.1 Eight PPS outputs — `CLBPPSOUT[0..7]`
The CLB exposes **8 outputs**, `CLBPPSOUT[0]..CLBPPSOUT[7]`, that reach external pins
through the **Peripheral Pin Select (PPS)** module. For each PPS output, the
**CLB Output 'n' Selection** latches pick **one of four unique BLE outputs** to drive
it.

![Figure 29-11. CLB Output 'n' Selections via the Configuration Interface](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-CA7D8485-795E-4F50-BF65-C6B1363B099E-low.png)

The **`CLBPPSCONn`** registers each hold two 4-bit `OESELn` fields, one per
`CLBPPSOUT` signal. `OESELn` controls the pin's output-enable (TRIS): values
`0000–0111` leave output-enable under `TRISx` control, while `1000–1111` tie the
output-enable to a specific BLE output (`BLE[3]`, `BLE[7]`, … `BLE[31]`) — this lets
the CLB drive a **tri-state bus** (dynamically enable/disable the driver from logic).

| `OESELn` | Output-enable source |
|----------|----------------------|
| `1111` | BLE[31] |
| `1110` | BLE[27] |
| `1101` | BLE[23] |
| `1100` | BLE[19] |
| `1011` | BLE[15] |
| `1010` | BLE[11] |
| `1001` | BLE[7] |
| `1000` | BLE[3] |
| `0111`–`0000` | `TRISx` (normal pin control) |

See [§29.5 CLB Outputs](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-08B12C69-313D-4228-83D3-9F1BBA59CBC3.html)
and [§29.5.1 CLB PPS Output Selections](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-A8A3A92F-FC15-4B5B-A6E6-CD25C99EAFA4.html).

### 4.2 Internal peripheral connections
BLE outputs are also routed **internally** to other peripherals (no pin needed), and
are fed back as possible BLE inputs. Per data-sheet Table 29-2:

| Peripheral | Function driven by the CLB |
|------------|----------------------------|
| ADC | ADC auto-conversion trigger source |
| CCP | CCP capture source |
| TMR0 | TMR0 clock input |
| TMR1 | TMR1 clock input / TMR1 gate source |
| TMR2 | TMR2 clock input / TMR2 external reset source |

> **These connections are per-BLE constrained** (official CLB training, "where can the
> BLE outputs go to"): each peripheral input can be driven only by a **subset of the 32
> BLE outputs** — e.g. TMR0-clock from very few BLEs, TMR1-clock/gate and TMR2-clock from
> one group, TMR2-external-reset and ADC-trigger from a wider set; tri-state/OE control
> only from the **odd** PPS outputs; interrupts on `IF0..3`. When offloading work to a
> timer/CLC (the recommended way around CLB routing limits, §10.3/§10.6), pick a peripheral
> whose CLB-driving BLE set the router can actually reach.

### 4.3 Interrupts — four of them
The CLB provides **4 interrupts**. Each **CLB Interrupt Selection** latch picks one of
the **32 BLE outputs** as the trigger; a **positive edge** on the selected output sets
the corresponding `CLB1IFn` flag (in the PIR registers), and if `CLB1IEn` is set, an
interrupt is generated.

![Figure 29-12. CLB Interrupt Selections](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-77FA33E9-F7CF-4C5D-A8E2-C6174783789D-low.png)

See [§29.7 CLB Interrupts](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-47F2A9DA-BE9A-4273-B2E5-E5360E69DE4E.html).

---

## 5. Clocking

The CLB clock is selected with the **`CLBCLK`** register (`CLK[3:0]` field). The
selected source passes through a **configurable clock divider** (set by the CLB Clock
Divider latches in the netlist); the divider output is **`BLE_clk`**.

**`BLE_clk` is the single synchronous clock of the whole fabric** — it drives:
- all **32 BLE output flops**,
- the **dedicated 3-bit counter**, and
- the **`CLBSWIN`** register synchronization.

### `CLBCLK` clock sources (Table 29-4)

| `CLK[3:0]` | Clock source |
|-----------|--------------|
| `0000` | No clock selected |
| `0001` | `CLBIN0PPS` (external pin) |
| `0010` | `CLBIN1PPS` (external pin) |
| `0011` | `CLBIN2PPS` (external pin) |
| `0100` | `CLBIN3PPS` (external pin) |
| `0101` | `FOSC` (system clock) |
| `0110` | `HFINTOSC` |
| `0111` | `LFINTOSC` |
| `1000` | `MFINTOSC` (500 kHz) |
| `1001` | `MFINTOSC` (32 kHz) |
| `1010` | `EXTOSC` (external oscillator/crystal) |
| `1011` | `ADCRC` |
| `1100` | `TMR0_overflow_OUT` |
| `1101` | `TMR1_overflow_OUT` |
| `1110` | `TMR2_postscaled_OUT` |
| `1111` | Reserved |

So the fabric can be clocked from the system clock, any internal oscillator, an
external oscillator, a timer overflow/postscaler, the ADC RC clock, or one of four
PPS input pins — then divided down to the desired `BLE_clk` rate.

> Note: a fabric clocked from a **pin or peripheral** is asynchronous to `FOSC`. Using
> `FOSC`/`HFINTOSC` gives the fastest, CPU-synchronous fabric. For purely
> combinational designs (no flops, no counter) a clock is not strictly required.
>
> **Observed in our setup:** clocking the fabric from an external pin
> (`CLK[3:0] = 0001`, `CLBIN0PPS`) **works** — a counter clocked from a 50 kHz pin
> divided it correctly (50 kHz → 195 Hz / 98 Hz). Separately, in our project the
> `HFINTOSC` source (`0110`) appeared to leave `BLE_clk` **not running** for clocked
> designs, and `FOSC` (`0101`) was reliable — but the data sheet lists `HFINTOSC` as a
> normal CLB clock source, so this is most likely a **local init/clock-setup issue on our
> side**, not a silicon limitation; if you hit it, check oscillator-enable/`OSCEN` and the
> CLB init order rather than assuming `HFINTOSC` is unusable.

See [§29.6 CLB Clock Selection](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-A2EE2376-A54B-45A4-AED1-9D95FE109A92.html)
and [§29.9.6 CLBCLK](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-CF8A4C61-AEE5-4A6D-8D23-E7754E57A4B8.html).

---

## 6. Configuration & load sequence (summary)

From [§29.8 CLB Configuration](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-F832DBF6-F9D2-4F5F-984D-2AA7CEE01416.html):

1. In the Configuration Interface: select CLB inputs, edge-detector modes, BLE
   inputs, LUT contents, flop selects, interrupt sources, PPS output selections,
   counter stop/reset/output selections, and the clock divider.
2. The Configuration Interface writes the resulting **netlist into Program Memory**.
3. Select the clock source via `CLBCLK`; set the PPS output-enable via `CLBPPSCONn`.
4. Configure the **NVM Scanner** (with the CRC module) and run it to load the netlist
   into the CLB latches/LUTs.
5. Set the **`EN`** bit in `CLBCON` to enable the module.

| Register | Role |
|----------|------|
| `CLBCON` | `EN` (module enable), `BUSY` (CLBSWIN sync busy) |
| `CLBCLK` | `CLK[3:0]` clock source select |
| `CLBSWINU/H/M/L` | 32-bit software input into the LUTs |
| `CLBPPSCON1..4` | `OESELn` output-enable select for `CLBPPSOUT[0..7]` |

---

## 7. How the bitstream is loaded (in detail)

The CLB has **no register you write the logic into**. Its configuration — the
"bitstream", i.e. the synthesized **netlist** — lives in **Program Flash Memory
(PFM)** and is copied into the CLB's internal latches and LUTs **at run time** by the
**NVM Scanner** working together with the **CRC** engine. This chapter documents that
mechanism register by register, as verified on this project's PIC16F13145.

### 7.1 What "the bitstream" actually is
- A sequence of **N 14-bit words** (one program-memory word each; every value
  ≤ `0x3FFF`). On this project the design synthesizes to **102 words**
  (`CLB_BITSTREAM_LENGTH` in `clb1_defs.h`).
- It is placed in a dedicated PFM section — a **PSECT `clb_config`**
  (`class=STRCODE, delta=2`) bracketed by linker symbols `_start_clb_config` /
  `_end_clb_config`, at a fixed address (e.g. `0x1000`). In this repo that is
  `clbBitstream.S`.
- The **packing** (which bit maps to which LUT entry, input/output-select latch,
  counter or clock-divider bit) is produced by the CLB synthesizer and is
  **undocumented** — it cannot be hand-authored, which is why the synthesizer is
  mandatory.

### 7.2 The three actors
| Actor | Role in the load |
|-------|------------------|
| **PFM** | Holds the netlist words at `[_start_clb_config .. _end_clb_config]`. |
| **NVM Scanner** (`SCANxxx`, ch. 19) | Fetches words from a PFM address range, one per cycle, from `SCANLADR` up to `SCANHADR`. |
| **CRC module** (`CRCCONx`) | The scanner only runs *in conjunction with* the CRC engine: `CRCEN` **and** `CRCGO` must be set before the scan starts, or it aborts. |

`SCANDPS.DPS` chooses the destination of the fetched data: **`DPS = 1` → CLB**
(`DPS = 0` → CRC accumulator). For a CLB load you set `DPS = 1`.

### 7.3 The load sequence, register by register
**Preconditions** (bare-metal must do these; MCC does them for you):
clear the relevant **PMD** bits — `PMD0.NVMMD/CRCMD/SCANMD = 0`, `PMD4.CLBMD = 0`;
select the CLB clock with `CLBCLK`; set `CLBPPSCONn` output-enables as needed. The
CLB must be configured/initialized (clock, PPS) *before* the scanner is started
([§19.9](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-70881DFD-BCC3-45C6-8DD3-320F5DE9ADC9.html)).

1. **Set the scan range** (only writable while `SGO = 0`):
   - `SCANLADRH:L = _start_clb_config`
   - `SCANHADRH:L = _start_clb_config + CLB_BITSTREAM_LENGTH − 1` (end address is
     **inclusive** → the `−1`).
2. **Route the scanner to the CLB:** `SCANDPS.DPS = 1`.
3. **Pick burst mode:** `SCANCON0.MD = 0b01` (the whole range is scanned in one
   uninterrupted burst).
4. **Enable the scanner:** `SCANCON0.EN = 1`.
5. **Enable the CRC engine FIRST:** `CRCCON0.EN = 1`, then `CRCCON0.GO = 1`.
   *(This must happen before step 6 — see §7.4.)*
6. **Start the scan:** `SCANCON0.SGO = 1`.
7. **Wait for completion:** poll `SCANCON0.BUSY` until it reads `0`. The scanner
   clears `SGO` itself once `SCANLADR` increments past `SCANHADR`.
8. **Tidy up:** clear `CRCCON0.GO` / `CRCCON0.EN` and `SCANCON0.EN` if desired.
9. **Enable the fabric:** `CLBCON.EN = 1` — only now does the CLB start running with
   the freshly loaded netlist.

```c
// --- CLB bitstream load (NVM scanner + CRC), bare-metal ---
extern const uint16_t __at(0x1000) clb_config[CLB_BITSTREAM_LENGTH]; // PSECT clb_config

PMD0bits.NVMMD = 0; PMD0bits.CRCMD = 0; PMD0bits.SCANMD = 0;
PMD4bits.CLBMD = 0;

CLBCLK = 0x05;                 // BLE_clk source = FOSC (32 MHz)

SCANLADR = START_ADDR;         // _start_clb_config
SCANHADR = START_ADDR + CLB_BITSTREAM_LENGTH - 1;   // inclusive end
SCANDPS  = 0x01;               // DPS = 1 -> route scan data to the CLB
SCANCON0bits.MD = 0b01;        // burst mode
SCANCON0bits.EN = 1;           // enable scanner

CRCCON0bits.EN = 1;            // CRC engine ON ...
CRCCON0bits.GO = 1;            // ... and running  (BEFORE SGO!)

SCANCON0bits.SGO = 1;          // start the scan
while (SCANCON0bits.BUSY) { }  // wait until the range is consumed

CLBCON0bits.EN = 1;            // enable the CLB fabric
```

### 7.4 Why the CRC must be enabled first (the `DABORT` trap)
`SCANCON0.DABORT` (Scanner Abort) **resets to `1`** and is asserted whenever
`SCANLADR` points to an invalid NVM address **or the CRC is disabled**. So if you set
`SGO` *before* `CRCEN`/`CRCGO`, the scan aborts on the spot, **nothing is loaded**,
and every `CLBPPSOUT` reads static. The data sheet states it plainly:

> *"`CRCEN` and `CRCGO` bits must be set before setting the `SGO` bit."*
> — [§19.14.8 SCANCON0](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-1D25DDB1-247C-47F5-A674-00598F605921.html)

This was the single biggest load bug found on this project (see `readme_clb.md` §5/§6).

### 7.5 Scanner modes — why burst
`SCANCON0.MD[1:0]` selects how the scanner shares the memory bus
([§19.14.8](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-1D25DDB1-247C-47F5-A674-00598F605921.html)):

| `MD` | Mode | Use |
|------|------|-----|
| `00` | Concurrent | scanner yields the bus to the CPU between fetches |
| `01` | **Burst** | scanner takes the bus until the whole range is done — **used for the one-shot CLB load** |
| `10` | Peek | single-access |
| `11` | Trigger | scan advances on a hardware trigger (`SCANTRIG.TSEL`) |

A simple "start then poll `BUSY`" loop loads reliably in **burst**; concurrent mode
did **not** load dependably in that pattern on this project.

### 7.6 Where this sits in the overall flow
The §6 summary is the *design-time* path (Configuration Interface → netlist → PFM).
This chapter is the *run-time* path: the scanner copies that PFM image into the live
CLB latches every time the firmware initializes the module. The two meet at the
`clb_config` PSECT — the synthesizer writes it, the scanner reads it.

Reference sections:
[§19.7 Scanner Overview](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-33BD734F-0E59-483F-B4F6-C1A19F5E7121.html) ·
[§19.9 Configuring the Scanner](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-70881DFD-BCC3-45C6-8DD3-320F5DE9ADC9.html) ·
[§19.14.9 SCANLADR](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-17C094F2-4543-41AF-A253-19DCBDAD3A0E.html) ·
[§19.14.10 SCANHADR](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-6A06EDB7-8F29-40DA-BBEF-DA643D1E46FF.html) ·
[§19.14.11 SCANDPS](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-31206AE5-B352-46E6-9206-128A27F75B15.html) ·
[§19.14.1 CRCCON0](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-A2EE4555-15AB-4887-8C20-613D7EB8DF77.html) ·
[§29.8 CLB Configuration](https://onlinedocs.microchip.com/oxy/GUID-A766082F-E194-4137-9D97-0F13252F7C55-en-US-11/GUID-F832DBF6-F9D2-4F5F-984D-2AA7CEE01416.html).

---

## 8. How to author a CLB design

§6 and §7 cover *configuring* and *loading* a finished netlist. This section is the
step **before** that: producing the netlist in the first place. There are two
front-ends for entering the logic, both feeding the same synthesizer back-end.

### 8.1 Two ways to enter the logic
| Method | How | Best for |
|--------|-----|----------|
| **Schematic** | The MCC Melody **CLB editor** in MPLAB X: drag-and-drop gates, flip-flops and the 3-bit counter; wire them visually. No HDL. | Small glue logic, quick experiments. |
| **HDL (Verilog) + constraints** | Write a Verilog module plus a pin-constraint `.xdc` file. Synthesizable, diff-able, automatable. | Parametric/larger designs, version control, CI. **This repo uses this** ([clb/clb_halfbridge.v](clb/clb_halfbridge.v) + `clb/clb_halfbridge.xdc`). |

### 8.2 The synthesizer (back end)
**The schematic editor is a GUI front-end for Verilog** — per the official "CLB
Synthesizer Tips & Tricks" training, *"behind the scenes, the schematic editor generates
Verilog code which eventually is synthesized."* So the two front-ends are **not** two
different pipelines: a schematic is turned into Verilog and then both go through the
**same** synthesizer (Yosys + a VPR place-and-route step), which emits the 14-bit
bitstream words (§7.1). (Consequence: a working official *schematic* example and an
equivalent hand-written *Verilog* design exercise the identical back-end — differences in
outcome come from the design/config, not from "schematic vs Verilog".) Three ways to run it:

- **Web app** — `logic.microchip.com/clbsynthesizer` (browser, no install).
- **CLI** — `pyclbsynthesizer` (pip): e.g.
  `python -m pyclbsynthesizer synthesize -d 131 <folder> -b` prints the hex words
  (`-d 131` = PIC16F13145; the folder needs one `main.v` + one `main.xdc`). Backends:
  `cont` (`dev.logic.microchip.com/continuous`, default) or `local`
  (`localhost:8001`).
- **Local Docker backend** — the `clb-backend` image run with `--host local`, for
  fully offline, version-pinned, reproducible builds.

This repo wraps the CLI in [clb/synth.py](clb/synth.py), which emits `clbBitstream.S`
+ `clb1_defs.h`. See `readme_clb.md` §4 for the full run order.

### 8.3 Verilog port & pin conventions
The synthesizer recognizes specific **reserved port names** on the top module
(empirically established for the PIC16F13145; map them to pins in the `.xdc`):

| Verilog port / attribute | Meaning |
|--------------------------|---------|
| `CLK` | The global `BLE_clk`. **Leave it UNMAPPED** in the `.xdc` — mapping it to an input pin yields *"clock signal could not be routed"*. |
| `IN0..INn` | Muxed inputs. `(* pincfg.INx.mux = 7'd<code> *)` selects the source signal; `(* pincfg.INx.syncmode.sync *)` enables the synchronizer. |
| `CLBSWIN0..n` | Software inputs (bits of `CLBSWIN`). |
| `PPS_OUT0..7` | External outputs → `CLBPPSOUT[n]` → pin via PPS. |
| `CLB_IRQ0/1` | Interrupt outputs. |
| `(* syscfg.CLKDIV = 3'd<n> *)` | The clock-divider setting. |

**Empirically-confirmed authoring rules (headless `pyclbsynthesizer` flow — verified on
this silicon, see §10):**

- **The top module name MUST equal the `.v` filename stem.** `pyclbsynthesizer` picks the
  single `.v` in the folder as top and derives the expected module name from the filename
  (`counter_2tap.v` → `module counter_2tap`). A mismatch → *"top-module '…' was not found"*.
- **`design` is a reserved word** — do **not** name the file `design.v` / the module
  `design` (→ *"syntax error, unexpected design"*).
- **Every output must be registered through a BLE flop** (clocked by `CLK`). A purely
  combinational / asynchronous design (`assign o = …;` with no flop) **does not route at
  all** (*"VPR failed to route"*). Put the result in an `always @(posedge CLK)` register.
- `.xdc` rule: **no `#` comment lines** — the constraint validator rejects them.
- One `.xdc` + one `.v` per design folder; `--indir <folder>` selects it
  ([clb/synth.py](clb/synth.py)).

### 8.4 Writing synthesizable Verilog for the CLB
The synthesizer accepts standard synthesizable Verilog (and the SystemVerilog `logic`
type). To produce code that **maps cleanly**, follow these rules (from the official
"Verilog for the CLB" training, slide "Tips, tricks and takeaways", plus §8.3/§10):

**Style rules (which construct writes which net):**
- Use **`reg`** for any net driven by a flip-flop (assigned inside an `always` block);
  use **`wire`** for nets driven by a gate primitive or a continuous `assign`.
- **Gate primitives** (`buf not` — 1 input; `and nand or nor xor xnor` — 2+ inputs) are
  instantiated **outside** `always` blocks; their output must be a **`wire`**.
  Syntax: `<gate> <instance>(<output>, <input1>, <input2>, …);`.
- **Continuous `assign`** only outside `always`, writing a `wire`.
- **Non-blocking `<=`** only **inside** `always`, writing a `reg`. (A `<=` inside an
  `assign` is a syntax error the synthesizer rejects.)
- `always @(posedge CLK)` blocks use `begin … end`; **`CLK` is the one reserved clock**
  (§8.3). You may **mix** gate-level, dataflow and behavioral styles in one module.

**CLB-specific musts (recap — these decide whether it maps):**
- **Module name = `.v` filename stem**; never name it `design` (§8.3).
- **Register every output** through a `posedge CLK` flop — pure-combinational top-level
  outputs are glitch-prone and, in this flow, often won't route (§8.3/§10.2a/§10 training).
- Inputs come in as `INx` (pin/peripheral via `pincfg.INx.mux`, with a synchronizer mode)
  or `CLBSWINx` (software); outputs leave as `PPS_OUTn` (mapped in `.xdc`). See §10.2 for
  the input caveats and the required `CLBSWIN`/synchronizer handling.
- **Every input must actively affect an output, and no output may be constant** — the
  synthesizer **optimizes such logic away** and then errors ("port was optimized away").

**Numbers / vectors (write them sized):**
- Sized literals: `4'd10` (4-bit dec), `8'h2A` (hex), `1'b0` (bit); `_` allowed for
  readability (`6'b10_1010`). Unsized numbers default to ≥32-bit — avoid them.
- Vectors: `reg [3:0] cnt;` (MSB first). **Keep widths small** — wide counters and many
  output taps hit the routing limits in §10.3 (the CLB has only 32 BLEs).

**SystemVerilog:** the `logic` data type and basic operators are fine; **verification
constructs (classes, OOP, testbench features) are *not* synthesizable** — use only the
synthesizable subset in a CLB design.

### 8.5 Synthesizable building blocks (templates)
Canonical, CLB-ready templates (adapted from the official examples: registered outputs,
`CLK` as the clock, module name = filename). Use these as starting points.

```verilog
// Free-running counter with two output taps  (file: clkdiv.v)
(* syscfg.CLKDIV = 3'd0 *)
module clkdiv (CLK, o0, o1);
    input CLK; output o0, o1;
    reg [8:0] cnt = 0;
    always @(posedge CLK) cnt <= cnt + 9'd1;
    assign o0 = cnt[7];          // BLE_clk / 256
    assign o1 = cnt[8];          // BLE_clk / 512
endmodule                        // xdc: o0->PPS_OUT0, o1->PPS_OUT1
```
```verilog
// D flip-flop with enable + synchronous reset  (file: dff_en_rst.v)
(* syscfg.CLKDIV = 3'd0 *)
module dff_en_rst (CLK, RST, en, d, q);
    input CLK, RST, en, d; output q; reg q = 0;
    always @(posedge CLK)
        if (RST)      q <= 1'b0;
        else if (en)  q <= d;     // a DFF with EN+RST costs 2-3 LUT inputs (§10.3)
endmodule
```
```verilog
// Modulo-N counter / divider  (file: mod_n.v) — self-contained, no external data input
(* syscfg.CLKDIV = 3'd0 *)
module mod_n (CLK, o0, o1);
    input CLK; output o0, o1;
    reg [2:0] cnt = 0; reg o0 = 0, o1 = 0;
    always @(posedge CLK) begin
        if (cnt == 3'd4) cnt <= 3'd0; else cnt <= cnt + 3'd1;  // mod-5
        o0 <= (cnt == 3'd0);      // 1/5 duty strobe
        o1 <= cnt[1];
    end
endmodule
```
```verilog
// Registered positive-edge detector on a pin input  (file: posedge_det.v)
// NOTE: external data inputs need the right synchronizer mode AND were unreliable
// in our flow (§10.2). Validate on hardware before relying on this.
(* syscfg.CLKDIV = 3'd0 *)
module posedge_det (CLK, IN0, o0);
    (* pincfg.IN0.mux = 7'd0 *) (* pincfg.IN0.syncmode.sync *)
    input CLK, IN0; output o0;
    reg d = 0, o0 = 0;
    always @(posedge CLK) begin
        d  <= IN0;
        o0 <= IN0 & ~d;           // one CLK-wide pulse on each rising edge
    end
endmodule
```

---

## 9. CLB vs CLC vs CWG — when to use which

The PIC16F131xx family has several ways to build hardware logic. Pick the smallest
one that fits:

| Block | What it is | Strengths | Use when |
|-------|-----------|-----------|----------|
| **CLC** (Configurable Logic Cell) | A handful of fixed cells (typically 4), each a small AND/OR array + one flip-flop, configured purely with registers. | Trivial to set up, deterministic, rock-solid, no synthesis/bitstream. | Small combinational glue, a single flip-flop, gating two or three signals. |
| **CWG** (Complementary Waveform Generator) | A dedicated half-/full-bridge driver with built-in dead-time. | Purpose-built for power switching. | Driving a half/full bridge — **but the PIC16F13145 does *not* have a CWG.** |
| **CLB** (this document) | A 32-BLE programmable fabric, defined by a synthesized bitstream. | Much larger/arbitrary logic and state machines in one block. | Logic too big for the CLCs, or custom state machines — accepting the synthesis step and the mapping caveats in §10. |

Because the PIC16F13145 has CLCs and a CLB **but no CWG**, this project builds its
half-bridge dead-time from **CLB + CLC + TMR2** rather than a CWG (see §11).

---

## 10. Empirical findings from our setup (NOT general CLB limits)

> ⚠️ **Scope & status — read first.** Everything in §10–§11 is an **empirical result
> from one specific setup**: the **headless `pyclbsynthesizer` Verilog flow**, **one
> silicon revision**, and **automated verification through PPS outputs + a logic
> analyzer**. In that setup, many designs failed and only simple *registered counter*
> designs were robust.
>
> **These results conflict in places with the data sheet and with official internal CLB
> examples**, which demonstrate considerably more working functionality on this same part
> — e.g. a **quadrature decoder** (external inputs, rising/falling-edge detection,
> debounce), **input-synchronizer demos** that drive `CLBIN0PPS` from `TMR0_OUT` and
> capture the waveforms, **LUT / PPS-OE** examples that use `CLBIN0PPS` for reset/mux/
> enable, and a **4-bit counter with enable and reset**. The official **silicon errata**
> lists **no CLB-specific defect** (it covers ADC T_AD, power-down current, and the PFM
> first-instruction fetch).
>
> Therefore the failures below are **most likely toolflow / mapping / init / test-setup
> issues, not silicon limitations.** State them as *"X did not work in our flow"* — never
> as *"the PIC16F13145 CLB cannot do X."* If you need a feature that failed here, **start
> from an MCC or official reference design** rather than trusting these results.

### 10.0 How these findings were established (and the verification's limits)
A capability suite ([clb_analyze.py](clb_analyze.py) + `clb/catalog/`) runs ~15 minimal
single-feature Verilog designs through **two gates** and records the result for each
(report: `clb_capability_report.html`):

- **Gate A — synthesis / place-and-route** (software): does it route? word count? error?
- **Gate B — silicon**: build → flash → measure on **all four** wired pins
  (RC0→D0 … RC3→D3) with a generic firmware fixture (`clbraw on` routes `CLBPPSOUT0..3`
  → RC0..3; `clbraw in` feeds a PWM into the CLB on RC3; `clbsw <hex>` drives `CLBSWIN`).

Verdicts: **WORKS** / **ROUTE_FAIL** (Gate A) / **HW_DEAD** (routed + built but static on
silicon). Synthesis is **deterministic** (same `.v` → byte-identical bitstream), so these
results are reproducible **within this flow**.

> **What a logic analyzer can and cannot prove here.** An LA on the PPS pins is solid for
> *"this output is static"*. It is **not** sufficient to conclude *"this CLB function does
> not exist on silicon"*: it only sees what is actually routed to an observable pin, and a
> dead reading can equally be masked by **output mapping / OE / PPS / reset / clock / netlist
> load / timing / the test design itself**, or (for narrow/glitchy pulses) by sample rate and
> thresholds. The strong conclusions below would need corroboration — an official reference
> design, an internal known-good comparison, interrupt-flag/peripheral-trigger observation,
> and a scope for narrow pulses — before being treated as anything more than setup-specific.

### 10.1 What worked / failed in our flow (setup-specific)
Result of the suite (2026-06-15): **1 WORKS, 5 ROUTE_FAIL, 9 HW_DEAD** — *in this flow.*
(The data sheet and official examples show several of the "failed" categories working on
this part; see the scope note above. Read the table as "our flow", not "the silicon".)

| Construct (one feature each) | Gate A | Gate B | Verdict |
|------------------------------|:------:|:------:|:-------:|
| Free-running counter, **2 taps** (`cnt[7]`,`cnt[8]` → 2 outputs) | routes | 125 k / 62.5 k measured | ✅ **WORKS** |
| Free-running counter, **3 high-bit taps** (`cnt[7..9]`) | ❌ clock not routed | — | ROUTE_FAIL |
| Counter **wider than ~10 bits** (`cnt[11]`) | ❌ clock not routed | — | ROUTE_FAIL |
| **Two** independent counters | ❌ clock not routed | — | ROUTE_FAIL |
| **8-input** AND/OR (wide LUT) | ❌ VPR failed to route | — | ROUTE_FAIL |
| Pure **combinational / async** (no flop) | ❌ VPR failed to route | — | ROUTE_FAIL |
| Counter, **4 taps** (`cnt[6..9]` → 4 outputs) | routes | all four outputs static | ⚠️ HW_DEAD |
| Combinational logic from **`CLBSWIN`** (AND/OR/XOR, mux, passthrough) | routes | frozen — input never arrives | ⚠️ HW_DEAD |
| **Pin input** passthrough (`IN0` → out, registered) | routes | output dead (input present on pin) | ⚠️ HW_DEAD |
| **Shift register** / multi-flop delay line | routes | dead | ⚠️ HW_DEAD |
| Counter **+ gating** (`cnt[7] & sw`/`& IN0`) | routes | dead — *even the raw counter tap dies* | ⚠️ HW_DEAD |
| Counter **clocked by an external pin** (`CLBCLK = CLBIN0PPS`) | routes | RC0 = 50 kHz/256 = 195 Hz, RC1 = /512 = 98 Hz | ✅ **WORKS** |
| Data input from an **internal peripheral** (`IN0.mux` = PWM1_OUT etc., codes 16/44–49 swept) | routes | dead (output never follows the internal signal) | ⚠️ HW_DEAD |
| **Self-resetting modulo counter** (`cnt==4 ? 0 : cnt+1`, comparator + sync reset + output decode, 2 outputs) | routes | RC0 = clk/5 @ 20 %, RC1 = clk/5 @ 40 % (exact) | ✅ **WORKS** |

**The envelope that was robust *in our flow* (not a statement about the silicon):**

> In our setup the only consistently-working designs were small, self-contained *clocked*
> ones whose inputs are all internal — free-running **and** self-resetting/modulo counters,
> comparators on the counter state, output decode, registered outputs, ≤ ~2–3 outputs —
> clocked internally (`FOSC`) or from an **external pin** (`CLBCLK = CLBINxPPS`). In our
> flow we **could not get an external signal to work as a logic *data* input** (pin `INx`
> mux, `CLBSWIN`, and internal-peripheral mux all read static), and **≥ 4 simultaneous
> outputs** went dead even when self-contained and routed.
>
> **Caveat:** official internal examples *do* use `CLBIN0PPS` as a functional data input
> (quadrature decoder, input-synchronizer demos) and build larger counters with enable/
> reset — so the data-input and multi-output failures are very likely a **flow/mapping/
> setup problem on our side**, not a silicon boundary. Use this envelope as a pragmatic
> "known-good starting point for *our* toolchain", and consult a reference design before
> concluding a feature is unavailable.

### 10.2 The two findings that bit us first (flow-specific)

**(a) In our flow, register your outputs — pure combinational top-level outputs often
would not route.** The data sheet explicitly says the CLB implements **combinational,
sequential, or mixed** logic, so combinational logic *is* supported in general. But in
our headless Verilog flow, `assign o = a & b;` with no flop frequently gave *"VPR failed
to route"*, while wrapping the result in `always @(posedge CLK) r <= …;` was reliable.
Treat this as a **flow / design-style** rule for our toolchain, not a silicon limit — and
note it is exactly the kind of thing a different front-end (MCC schematic, official
example) may handle without trouble.

**(b) In our flow we could not get an external signal to work as a logic DATA input —
only as the CLOCK.** This is our most surprising finding **and the one most in tension
with official material**: the data sheet documents 16 selectable inputs, `CLBINxPPS`,
`CLBSWIN`, and synchronizer/edge/bypass paths, and **official internal examples use
`CLBIN0PPS` as a working data input** (quadrature decoder; input-synchronizer demos
driven from `TMR0_OUT`). So the most likely explanation for our result is a **setup /
mapping / init defect on our side**, not that the path is dead on silicon. What we
observed, precisely:

- **Data input via pin `IN0`** (`CLBIN0PPS`, registered passthrough): **dead.** The
  stimulus was confirmed on the pin (RC3 = 50 kHz) yet the output that should follow it
  stayed at 0 — **for every input-synchronizer mode** (`syncmode.sync`, `.async`,
  `.rising`, and no attribute were each built and measured; all dead). So within our flow
  it was not a matter of the `syncmode` attribute; we simply never got the data-input path
  to propagate. (Since official examples *do* drive `CLBIN0PPS` as data, the fault is most
  likely elsewhere in our setup — mux-code mapping, init order, or the test design.)
- **Data input via `CLBSWIN`** (software): ✅ **RESOLVED — it WORKS.** Our earlier "dead"
  result was a **firmware bug, not the CLB**: we wrote `CLBSWINL` without the **`CLBCON.BUSY`
  handshake**. After adding `while(CLBCONbits.BUSY){}` *before* writing U/H/M and *after*
  writing L (per DS 29.4.1 / the training, §2.3), a registered passthrough cleanly followed
  `CLBSWIN`: `clbsw 0xFFFFFFFF` → outputs high, `clbsw 0x0` → low, repeatably (verified on a
  2-output design). **So `CLBSWIN` is a usable runtime-data path** — the key enabler for an
  adjustable-parameter CLB design. *(The earlier all-ones-gave-0 was the missing handshake;
  with it, both outputs of a 2-output design responded. A 4-output variant left 2 outputs
  dead — that is the separate ≥4-output routing limit, §10.3, not a CLBSWIN issue.)*
  **Mapping caveat:** the synthesizer assigns each Verilog `CLBSWINk` to an **arbitrary
  physical `CLBSWIN[31:0]` register bit**, not bit `k` — a bit-walk showed Verilog
  `CLBSWIN0` landing on **register bit 2** in one design. So for a multi-bit runtime value
  (e.g. a divider period), discover the per-design bit positions (bit-walk, or read the
  netlist IPAD assignment) and have firmware write the value onto those scattered bits.
- **Data input from an internal peripheral** (`IN0.mux` set to PWM1_OUT etc.; codes
  16 and 44–49 each built and measured with PWM1 running internally): **also dead.**
  So the data-input path fails for **all three** source types — pin, software, and
  internal peripheral.
- **The same pin used as the fabric CLOCK** (`CLBCLK = CLBIN0PPS`, i.e. `CLK[3:0]=0001`):
  **works perfectly.** A counter clocked from the 50 kHz pin produced exactly
  `cnt[7] = 50 kHz/256 = 195 Hz` and `cnt[8] = 98 Hz`. This proves the external signal
  **does** reach the fabric and the routing is correct — the failure is specific to the
  **data-input** path, not signal routing.
- Combining a working free-running counter with input-dependent gating kills the
  **whole block** — even the ungated counter reference output goes dead.

**The pattern in our data (and the genuinely good news):** the only thing that failed was
the **external-data-input path**; everything that depends solely on **internal state
worked** — a self-resetting modulo counter (`cnt==N ? 0 : cnt+1`), comparators on the
count, and output decode all ran correctly (verified: a mod-5 counter produced exact
clk/5 outputs). So even *within our flow* the earlier "edge-reset counter never resets"
failure was not because resettable counters are unsupported — it was because that reset
was driven by an external **input edge** (the path we couldn't get working). Internal
resets/comparators are fine.

**Practical consequence for our toolchain:** the reliable way *we* got an external signal
into CLB logic was as **`BLE_clk` (`CLBCLK = CLBINxPPS`)**, then processed with internal
logic (counter, comparator, modulo/divide, decode). Given our trouble with `INx`/`CLBSWIN`
data inputs, we route run-time data/levels through **CLC + timers** (§10.6, §11) — *as a
workaround for our flow*, not because the CLB data path is unusable in general (official
examples show it working). Root cause of our data-input failure remains unidentified;
reproducing an official input example would be the way to settle it.

**Before concluding inputs don't work, check these (from the official training) — we did
not fully control for them:**
- **Pin inputs need the right synchronizer mode.** A *Direct input* (synchronizer
  bypassed) is glitch-/metastability-prone; use the **synchronized** or an **edge-detector**
  mode (each adds **2 CLB-clock cycles** of delay). A registered output is also required
  for a stable result (§10.2a). Our pin-input attempts may have hit a synchronizer/clock
  mismatch rather than a dead path.
- **`CLBSWIN` has *no* input synchronizer.** Data is transferred to the fabric **only when
  the low byte `CLBSWINL` is written** (which asserts the internal `CLBSWIN_SFR_WR_HOLD`);
  software must wait on **`CLBCON.BUSY`** and not write again mid-transfer. If our writes
  didn't honour the `BUSY` handshake, or the design read the wrong `CLBSWIN[31:0]` bit
  (the bit→BLE mapping is fixed, §10.3), the value would look "stuck".
- The robust path to bring a fast external signal *in* and observe it is still the
  **clock** (`CLBCLK = CLBINxPPS`), which worked for us unambiguously.

### 10.3 Place-and-route is fragile and non-monotonic
**This is officially acknowledged.** The CLB training states plainly that *"there are
designs which theoretically should fit in the CLB, but they do not — that is due to the
routing limitations of the CLB"* and that *"the synthesizer is not good enough; we can
help it."* So routing failures on apparently-small designs are a known property, not a
mystery — what we saw matches it:
- `cnt[8]` routes; `cnt[9]` fails *"clock could not be routed"*.
- **2** high-bit output taps route; **3** do not — *but* a particular **4**-tap set
  (`cnt[6,7,8,9]`) *did* route while a 3-tap set (`cnt[7,8,9]`) did **not**. Routability
  is not monotonic in the number of outputs; small tap changes flip it.
- A *lone* clocked output won't route — add a second output.
- **Don't MUX/combine counter bits with an input.** A free-running counter whose outputs
  are **direct** taps (`assign o = cnt[k];`) routes (that's the proven shape). But routing
  the counter through a **mux selected by `CLBSWIN`/`INx`** (`o = sel ? cnt[a] : cnt[b]`)
  fails *"clock could not be routed"* (tested 8:1 and 4:1, registered and combinational).
  Likewise a **programmable counter** (period/reset/reload from `CLBSWIN`) either fails to
  route, or routes but the P&R **silently drops** all but ~2 of the period bits (a 4-bit
  programmable divider behaved as ~2 functional bits → only ~4 distinct frequencies). So a
  *runtime-selectable frequency* inside the CLB is **not** achievable beyond ~2 direct taps;
  generate fixed-tap frequencies and switch them in firmware via PPS, or make the frequency
  with a PWM/timer outside the CLB.
- Net: treat Gate A as a coin toss for anything beyond the proven shape, and **always
  confirm on silicon (Gate B)** — a clean synthesis means nothing (it can even route with
  inputs silently dropped).

**Why this happens — the routing matrix is sparse (from the official training).** Plan
designs around these fixed connection rules; they explain most of the failures above:
- **BLE LUT = 4 inputs.** Any ≤4-input Boolean function fits one BLE; **5+ inputs need
  ≥2 BLEs.** A **D-FF with Enable or Reset costs 2–3 of those 4 LUT inputs**, leaving only
  a 1–2-input function — so "gated/resettable register + logic" eats BLEs fast.
- **BLE inputs A/B/C/D can only source from fixed bit-slices**: other-BLE outputs
  `[7:0]/[15:8]/[23:16]/[31:24]` → A/B/C/D; synchronized inputs `[3:0]/[7:4]/[11:8]/[15:12]`;
  SW-input bits and counter outputs likewise sliced. Not every signal can reach every LUT
  input — this is why some nets "can't be routed" though BLEs are free.
- **Each CLB PPS output can only be driven by a specific subset of BLEs**, and **only the
  odd PPS outputs (1,3,5,7) can do tri-state/OE control**. Picking a different
  `PPS_OUTn` for a signal can remove a routing bottleneck (the training shows reassigning
  outputs to cut BLE usage). This is the likely reason our multi-tap/lone-output cases
  flipped between route/fail.
- Only **32 BLEs** total; the synthesizer also burns BLEs purely as **routing bridges**.
- Mitigation (official, slide "what if something cannot be connected"): **move logic out
  of the CLB** — use a **CLC** for simple input logic *before* the CLB, **TMR1 gate mode**
  to count events, and spread signals across alternate PPS outputs/interrupts. (This is
  exactly the §10.6/§11 approach.)

### 10.4 Load-time traps (recap of §7 — silent failures)
- Enable **`CRCEN` + `CRCGO` before `SGO`**, or `DABORT` aborts the scan and every
  `CLBPPSOUT` reads static (§7.4).
- Use **burst** mode (`SCANCON0.MD = 0b01`); clear **PMD** bits
  (`NVMMD/CRCMD/SCANMD/CLBMD`); end address = `start + LEN − 1` (inclusive).
- Use a real running clock: **`CLBCLK = FOSC` (0x05)** worked reliably here. `HFINTOSC`
  (`0x06`) appeared to leave `BLE_clk` not running in our setup — likely a local
  oscillator-enable/init issue (the data sheet lists it as valid), so check `OSCEN`/init
  order rather than avoiding `HFINTOSC` outright.

### 10.5 Toolchain / authoring gotchas

**Synthesizer error classes (from the official training) — what they mean:**
- **"Port / logic was optimized away."** A gate output that is constant (e.g. an `OR`
  whose result is always 1), or an input that never affects any output, gets removed →
  the port disappears and synthesis errors. **Fix:** make sure every input actively
  contributes and no output is constant (§8.4).
- **Syntax error.** e.g. a non-blocking `<=` inside a continuous `assign`. **Fix:** keep
  `<=` inside `always`, `assign`/gates outside (§8.4).
- **"Design cannot be routed."** Either it genuinely doesn't fit (not enough BLEs) **or**
  it hits the routing limits (§10.3) though it "should" fit. **Fix:** shrink it / move
  logic to CLC+timers (§10.6) / reassign PPS outputs.
- **Schematic flow:** because the schematic is converted to Verilog (§8.2), an
  incompletely-wired schematic generates bad Verilog. The Design Checker normally disables
  *Synthesize* until it's fixed — **do not** enable *"Always allow synthesis"*, or you'll
  feed the faulty Verilog through and get errors.
- **Tip — simulate first.** The synthesizer (web + MCC Melody) has a **testbench editor +
  simulator**: drive the module's inputs with stimulus blocks and check the waveforms
  *before* synthesizing. (The official synthesizer is **online-only** — web or MCC, both
  need internet; our `pyclbsynthesizer`/Docker path is the offline alternative.)

- **Module name = `.v` filename stem**; `design` is reserved (§8.3).
- **Synthesis is deterministic**, but the default `--host cont` is a **rolling**
  backend that can change version over time. For reproducible builds pin to the
  **local Docker backend** (`clb-backend`, `--host local`), or just rely on the
  committed `clbBitstream.S` and don't re-synthesize unless the `.v` changes.
- **`build.bat` is intermittently flaky** (spurious exit 1 right after the `.S` is
  rewritten); a single retry clears it ([clb_analyze.py](clb_analyze.py) does this).
- **Device state is sticky:** after exercising `clbraw`/`pulse`/`pinid`, the working
  `clb on` half-bridge can come up half-dead until a **`reset`**. Re-synthesize the
  intended design, rebuild, flash, then `reset` before trusting a measurement.

### 10.6 The recipe that was reliable in our flow
*(A pragmatic starting point for our toolchain — not the limit of the part. If you need
more, base your design on an MCC / official reference example.)*
1. Keep CLB logic **self-contained and clocked, with ≤ ~2–3 outputs**: free-running or
   **self-resetting/modulo counters**, comparators on the count, and output-decode are
   all fine (a mod-N divider works). Register every output through `CLK`. Avoid ≥ 4
   simultaneous outputs (they go dead even when self-contained).
2. If you need the CLB to react to an external signal, feed that signal as the **fabric
   clock** (`CLBCLK = CLBINxPPS`) — that path works (verified). The counter can then
   divide / time off it. You can **not** use the signal as a logic *data* input.
3. Do **all** other input handling, gating, edge/level logic, and state in the **CLC
   cells** and **timers (TMR0/1/2, HLT)** — register-configured, deterministic, reliable.
4. Wire the CLB counter output to the CLC/timer inputs **through a pin (PPS loopback)**
   or an internal peripheral connection (§4.2) — do **not** rely on CLB *data* inputs.
5. Verify on hardware (Gate B). This is exactly what the half-bridge in §11 does.

> **Bottom line for an AI using this part *via our flow*:** the low-risk path that worked
> for us was to use the CLB as a bare clock/counter source and build gating, input
> conditioning, muxing and wider logic from CLC + timers. This is a **workaround tuned to
> our toolchain**, not a statement that the CLB can't do those things — official examples
> implement input conditioning, muxing and counters-with-reset inside the CLB. If you need
> that, reproduce an official/MCC example first.

---

## 11. Worked example: the half-bridge in this repo

A concrete application of everything above: a complementary **half-bridge** on
RC0 (high-side) / RC1 (low-side) with a **dead-time adjustable at run time**.

Following the pragmatic §10 approach *(chosen because of our flow's limits, not the
silicon's)*, the **CLB does only a free-running counter** that produces the PWM frequency
taps, and all the stateful, non-overlap logic is offloaded to reliable, register-configured
blocks:

- **CLB** → free-running counter → PWM taps (`cnt[7]`/`cnt[8]`, ~125 / 62.5 kHz) on
  `CLBPPSOUT0/1`.
- **TMR2 (HLT)** → edge-triggered monostable, retriggered by every PWM edge →
  dead-time = `dt × 31.25 ns`.
- **CLC1 / CLC2** → two D-flip-flops that turn PWM + the monostable pulse into the
  complementary, dead-timed HS / LS — **non-overlap guaranteed by construction**.

Hardware-verified across `dt = 2/5/10/20` with 0.000 % overlap. This is the textbook
illustration of the limitation in §10: *give the CLB only the counter; build the rest
from CLC + timer.* Full schematic, register map, measurements and the failure history
are in [readme_clb.md](readme_clb.md).

---

## 12. At a glance

| Aspect | PIC16F13145 CLB |
|--------|-----------------|
| Logic elements | **32 BLEs**, each = 4-input LUT (16-bit) + optional output flop |
| Counter | 1 dedicated **3-bit** counter, clocked by `BLE_clk` |
| External/peripheral inputs | **16** selectable, each with an edge detector / synchronizer |
| Software inputs | **32-bit** `CLBSWIN` (bit-banged from firmware) |
| Feedback inputs | 3 counter bits + BLE outputs |
| Outputs to pins | **8** `CLBPPSOUT[0..7]` via PPS (each = 1 of 4 BLE outputs) |
| Internal outputs | ADC trigger, CCP capture, TMR0/1/2 clock/gate/reset |
| Interrupts | **4**, each from any of the 32 BLE outputs (positive edge) |
| Clock | `CLBCLK` source → divider → `BLE_clk` (feeds all flops, counter, CLBSWIN) |
| Fabric clock rate | up to `FOSC`; this project runs `BLE_clk = 32 MHz` (measured) |
| Configuration | Netlist in PFM, loaded by the NVM scanner, then `EN = 1` |
| Bitstream footprint | netlist of 14-bit PFM words (this design: **102**, `CLB_BITSTREAM_LENGTH`) |
| Authoring | MCC schematic *or* Verilog + `.xdc` → synthesizer (Yosys/VPR) → bitstream |

---

## 13. Glossary

| Term | Meaning |
|------|---------|
| **CLB** | Configurable Logic Block — the FPGA-like programmable logic fabric described here. |
| **BLE** | Basic Logic Element — the CLB's building block: a 4-input LUT plus an optional output flip-flop. The PIC16F13145 has **32**. |
| **LUT** | Look-Up Table — a 16-bit memory inside each BLE that implements any 4-input → 1-output combinational function. |
| **Output flop** | The flip-flop on a BLE's LUT output; the **BLE Flop Select** bit chooses combinational (LUT direct) vs. registered output. |
| **Bitstream** | Informal name for the synthesized CLB **netlist** stored as 14-bit PFM words and loaded into the fabric. |
| **Netlist** | The structural description (LUT contents, input/output selects, routing) the Configuration Interface emits; stored in PFM. |
| **Configuration Interface** | The design-time tool path (e.g. MPLAB CLB synthesizer fed from Verilog) that turns logic into the netlist. |
| **`BLE_clk`** | The single global fabric clock — output of the CLB clock divider. Clocks all 32 BLE flops, the 3-bit counter, and `CLBSWIN` sync. |
| **`CLBCLK`** | Register whose `CLK[3:0]` field selects the clock *source* (FOSC, *INTOSC, EXTOSC, a timer, ADCRC, or a PPS pin) feeding the divider. |
| **3-bit counter** | The CLB's one dedicated hardware counter; clocked by `BLE_clk`, stop/reset drivable from any BLE output, its 3 bits usable as BLE inputs. |
| **`CLBSWIN`** | 32-bit software-input register (`CLBSWINU:H:M:L`) the CPU bit-bangs into the LUTs; latched when `CLBSWINL` is written. |
| **`CLBIN0PPS..3PPS`** | PPS input registers that route external pins into the CLB (and can also be selected as the CLB clock source). |
| **`CLBPPSOUT[0..7]`** | The CLB's 8 fabric outputs routed to pins via PPS; each selects 1 of 4 BLE outputs. |
| **`CLBPPSCONn` / `OESEL`** | Registers/fields controlling each `CLBPPSOUT` pin's output-enable; can tie OE to a BLE output to drive a tri-state bus. |
| **Edge detector / Input synchronizer** | Per-input stage (16 of them) that makes a CLB input positive-edge, negative-edge, or bypassed; synchronizes to `BLE_clk`. |
| **PPS** | Peripheral Pin Select — the on-chip routing matrix mapping peripheral signals (incl. CLB I/O) to physical pins. |
| **PFM** | Program Flash Memory — non-volatile program store; holds the `clb_config` netlist words. |
| **PSECT** | A named linker section (XC8); here `clb_config` (`class=STRCODE, delta=2`) bracketed by `_start_clb_config`/`_end_clb_config`. |
| **NVM Scanner** | Hardware (`SCANxxx` registers) that fetches a PFM address range word-by-word; routes data to the CLB when `SCANDPS.DPS = 1`. |
| **CRC module** | CRC engine (`CRCCONx`); the scanner only runs with `CRCEN`+`CRCGO` set — required even when the goal is just to load the CLB. |
| **`SGO`** | Scanner GO bit (`SCANCON0`); starts the scan, auto-cleared when `SCANLADR` passes `SCANHADR`. |
| **`BUSY`** | Scanner-busy indicator (`SCANCON0`); poll until `0` to know the load finished. |
| **`DABORT`** | Scanner Abort (`SCANCON0`, resets to `1`); set if `SCANLADR` is invalid **or** the CRC is disabled → cause of a silent failed load. |
| **`DPS`** | Dedicated Peripheral Select (`SCANDPS`): `1` = scan data to CLB, `0` = to CRC. |
| **Burst mode** | `SCANCON0.MD = 0b01`; the scanner holds the bus and reads the whole range at once — the reliable mode for a one-shot CLB load. |
| **PMD** | Peripheral Module Disable — power-gating bits; the relevant ones (`NVMMD/CRCMD/SCANMD/CLBMD`) must be cleared before loading. |
| **Metastability** | Unstable flip-flop state risk if an *unsynchronized* (edge-detector-bypassed) input drives a BLE output flop. |
| **CWG** | Complementary Waveform Generator — a fixed-function dead-time peripheral the PIC16F13145 **lacks**, which is why the CLB is used for half-bridge logic in this repo. |
| **Place-and-route (P&R)** | The synthesizer step that assigns logic to physical BLEs and wires them; its routability is sensitive on this device (see `readme_clb.md`). |
