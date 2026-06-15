/**
 * @file main.c
 * @author M91221
 * @date 2026-06-13
 * @brief UART command line with hardware PWM (PIC16F13145 Curiosity Nano)
 *
 * Serial console over the PKOB-nano CDC (115200 8N1):
 *   RC4 -> EUSART1 TX   (target TX        -> debugger CDC RX)
 *   RC5 -> EUSART1 RX   (debugger CDC TX  -> target RX)
 *
 * Hardware PWM outputs (dedicated PWM modules, Timer2 time base):
 *   RC0 = PWM1 = signal A
 *   RC1 = PWM2 = signal B
 *   The device has only one PWM time base (Timer2), so both channels share
 *   a common, adjustable frequency; the duty cycle is independent per channel.
 *
 * Commands:
 *   help
 *   reset
 *   pulse freq <Hz>        - set the shared PWM frequency
 *   pulse a|b on|off       - enable/disable a channel output
 *   pulse a|b duty <0-100> - set the duty cycle of a channel (percent)
 *   pulse status
 */

// ---- Configuration bits (tokens verified against DFP 16f13145.html) ----
// CONFIG1
#pragma config FEXTOSC  = OFF            // external oscillator off
#pragma config RSTOSC   = HFINTOSC_32MHz // reset oscillator: HFINTOSC @ 32 MHz
#pragma config CLKOUTEN = OFF
#pragma config CSWEN    = ON
#pragma config FCMEN    = OFF
// CONFIG2
#pragma config MCLRE    = EXTMCLR
#pragma config WDTE     = OFF            // watchdog off
#pragma config LVP      = ON             // low-voltage programming (Curiosity Nano)

#define _XTAL_FREQ 32000000UL

#include <xc.h>
#include <stdint.h>
#include <string.h>

// Firmware identification banner. __DATE__/__TIME__ are filled in by the XC8
// compiler when main.c is compiled, so the timestamp identifies the running
// build. (Reflects the last compile of THIS file - rebuild after edits.)
#define FW_NAME   "Loop"
#define FW_BANNER FW_NAME " firmware | build " __DATE__ " " __TIME__

// ========================= PWM state / model =========================
// Timer2 PWM:  Fpwm = FOSC/4 / (N * prescale) = 8e6 / (N * prescale), N=T2PR+1.
// Duty 10-bit value DC = duty% * 4 * N / 100; duty fraction = DC / (4*N).
// Everything is computed in integers; the console formats values as x.xxx,
// so input and output are floating point without linking the float library.
#define FOSC_DIV4   8000000UL            // FOSC/4 = 8 MHz (PWM clock base)

static uint16_t g_period_n = 250;       // N = T2PR+1
static uint16_t g_prescale = 32;        // Timer2 prescaler (1..128)
static uint16_t g_dcA = 0, g_dcB = 0;   // current 10-bit duty values
static uint32_t g_mpctA = 50000;        // requested duty, milli-percent (x1000)
static uint32_t g_mpctB = 50000;
static uint8_t  g_enA = 0, g_enB = 0;   // channel enabled?

// Parse a fixed-point number ("33.3", "1000", "0.05") into milli-units (x1000).
// Returns 1 on success; fractional digits beyond 3 are ignored.
static uint8_t parse_milli(const char *s, uint32_t *out)
{
    uint32_t whole = 0, frac = 0, fdiv = 1;
    uint8_t seen = 0, dot = 0;
    while (*s == ' ') s++;
    for (; *s; s++) {
        char c = *s;
        if (c == '.' && !dot) { dot = 1; continue; }
        if (c < '0' || c > '9') return 0;
        seen = 1;
        if (!dot)             whole = whole * 10u + (uint32_t)(c - '0');
        else if (fdiv < 1000) { frac = frac * 10u + (uint32_t)(c - '0'); fdiv *= 10u; }
    }
    if (!seen) return 0;
    while (fdiv < 1000) { frac *= 10u; fdiv *= 10u; }   // scale to thousandths
    *out = whole * 1000u + frac;
    return 1;
}

// Parse the integer part of a number into a uint32 (saturating on overflow).
// Used for frequency input, where milli-scaling would overflow above ~4.3 MHz.
static uint8_t parse_u32(const char *s, uint32_t *out)
{
    uint32_t v = 0;
    uint8_t seen = 0;
    while (*s == ' ') s++;
    for (; *s && *s != '.'; s++) {           // integer part only
        if (*s < '0' || *s > '9') return 0;
        seen = 1;
        if (v > 429496729u) v = 0xFFFFFFFFu; // saturate -> rejected as out of range
        else v = v * 10u + (uint32_t)(*s - '0');
    }
    if (!seen) return 0;
    *out = v;
    return 1;
}

// Parse a hex number ("0x1F", "1f", "5") into a uint32. Returns 1 on success.
static uint8_t parse_hex(const char *s, uint32_t *out)
{
    uint32_t v = 0;
    uint8_t seen = 0;
    while (*s == ' ') s++;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    for (; *s; s++) {
        char c = *s; uint8_t d;
        if      (c >= '0' && c <= '9') d = (uint8_t)(c - '0');
        else if (c >= 'a' && c <= 'f') d = (uint8_t)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') d = (uint8_t)(c - 'A' + 10);
        else return 0;
        v = (v << 4) | d; seen = 1;
    }
    if (!seen) return 0;
    *out = v;
    return 1;
}


// Actual generated frequency in milli-Hz, from N and prescale (exact).
static uint32_t pwm_actual_mfreq(void)
{
    uint32_t d = (uint32_t)g_period_n * g_prescale;    // <= 32768
    uint32_t whole = FOSC_DIV4 / d;                    // Hz
    uint32_t frac  = (FOSC_DIV4 % d) * 1000u / d;      // milli-Hz remainder
    return whole * 1000u + frac;                       // <= 4e9, fits uint32
}

// Actual duty of a channel (from its DC) in milli-percent (exact).
static uint32_t pwm_actual_mpct(uint16_t dc)
{
    uint32_t denom = 4u * g_period_n;                  // <= 1024
    uint32_t whole = (uint32_t)dc * 100u / denom;
    uint32_t frac  = ((uint32_t)dc * 100u % denom) * 1000u / denom;
    return whole * 1000u + frac;
}

// =========================== Peripherals =============================
static void UART1_Init(void)
{
    TRISCbits.TRISC4 = 0;   // RC4 = TX -> output
    TRISCbits.TRISC5 = 1;   // RC5 = RX -> input
    ANSELCbits.ANSELC4 = 0; // digital
    ANSELCbits.ANSELC5 = 0; // digital (otherwise no RX input buffer)

    RC4PPS = 0x13;          // RC4 source = TX1/CK1 (table 18-2)
    RX1PPS = 0x15;          // EUSART RX input = RC5 (PORTC=010, pin5=101)

    // Baud rate 115200 @ 32 MHz, async, 16-bit BRG (BRGH=1, BRG16=1)
    BAUD1CON = 0x08;        // BRG16 = 1
    SP1BRGL  = 68;          // 32MHz/(4*(68+1)) = 115942 baud (+0.64 %)
    SP1BRGH  = 0;
    TX1STA = 0x24;          // TXEN = 1, SYNC = 0, BRGH = 1
    RC1STA = 0x90;          // SPEN = 1, CREN = 1
}

// Set one channel's duty from milli-percent; writes registers, stores state.
static void PWM_SetDuty(char ch, uint32_t mpct)
{
    if (mpct > 100000u) mpct = 100000u;               // clamp to 100.000 %
    uint32_t denom = 4u * g_period_n;                 // full-scale DC
    uint32_t dc = (mpct * denom + 50000u) / 100000u;  // round
    if (dc > 1023u) dc = 1023u;
    uint8_t dch = (uint8_t)(dc >> 2);
    uint8_t dcl = (uint8_t)((dc & 0x03u) << 6);
    if (ch == 'a') { g_mpctA = mpct; g_dcA = (uint16_t)dc; PWM1DCH = dch; PWM1DCL = dcl; }
    else           { g_mpctB = mpct; g_dcB = (uint16_t)dc; PWM2DCH = dch; PWM2DCL = dcl; }
}

// Pick prescaler + T2PR for the requested frequency (Hz), then re-apply duties.
// Returns 1 on success, 0 if the frequency is out of range (~244 Hz..4 MHz).
static uint8_t PWM_SetFrequency(uint32_t freq)
{
    if (freq == 0) return 0;
    for (uint8_t i = 0; i < 8; i++) {           // prescale = 1,2,4,...,128
        uint32_t prescale = 1UL << i;
        uint32_t denom = freq * prescale;
        uint32_t n = (FOSC_DIV4 + denom / 2u) / denom;   // (T2PR+1), rounded
        if (n >= 2u && n <= 256u) {
            g_period_n = (uint16_t)n;
            g_prescale = (uint16_t)prescale;
            T2PR  = (uint8_t)(n - 1u);
            T2CON = (uint8_t)(0x80u | ((unsigned)i << 4)); // ON=1, CKPS=i, OUTPS=1:1
            PWM_SetDuty('a', g_mpctA);           // period changed -> rescale duty
            PWM_SetDuty('b', g_mpctB);
            return 1;
        }
    }
    return 0;
}

static void PWM_Enable(char ch, uint8_t on)
{
    if (ch == 'a') { g_enA = on; PWM1CONbits.EN = on ? 1 : 0; }
    else           { g_enB = on; PWM2CONbits.EN = on ? 1 : 0; }
    // When EN=0 the module output is low, so the (PPS-routed) pin reads low.
}

static void PWM_Init(void)
{
    ANSELCbits.ANSELC0 = 0;             // RC0 digital
    ANSELCbits.ANSELC1 = 0;             // RC1 digital
    LATCbits.LATC0 = 0;
    LATCbits.LATC1 = 0;
    TRISCbits.TRISC0 = 0;               // RC0 = output (PWM1)
    TRISCbits.TRISC1 = 0;               // RC1 = output (PWM2)

    T2CLKCON = 0x01;                    // Timer2 clock = FOSC/4 (required for PWM)
    T2HLT    = 0x00;                    // free-running period mode

    PWM1CON = 0x00;                     // both PWM modules off until 'pulse .. on'
    PWM2CON = 0x00;

    PWM_SetFrequency(1000);             // default 1 kHz; sets T2PR/T2CON + duties

    RC0PPS = 0x2C;                      // RC0 <- PWM1 (table 18-2)
    RC1PPS = 0x2D;                      // RC1 <- PWM2
}

// ============== CLB half-bridge (RC0 = HS, RC1 = LS) =================
// Drives the CLB-synthesized half-bridge (clb/clb_halfbridge.v) with a runtime
// dead-time. The bitstream (clbBitstream.S) is streamed into the CLB by the NVM
// scanner; the dead-time is written live through CLBSWIN. While active, RC0/RC1
// are switched from the PWM modules to the CLB outputs, and PWM1 is the input
// waveform (set its frequency/duty with the normal `pulse freq` / `pulse a duty`).
//
// [SYNTH] constants must be matched to the synthesized design once
// clb_halfbridge.v has been run through the CLB Synthesizer (output PPS codes,
// the CLBSWIN bits carrying dt, and the BLE clock). Placeholders until then.
#include "clb1_defs.h"                     // generated by clb/synth.py: CLB_BITSTREAM_LENGTH
extern uint16_t start_clb_config;          // bitstream start label from clbBitstream.S

// ===== Timer+CLC dead-time architecture (the CLB only generates the PWM) =====
// The CLB free-running counter outputs pwm (~62.5 kHz, CLBPPSOUT0) onto RC2. That
// pwm feeds TMR2 (HLT edge monostable, T2PR = dt) and two CLC D-flip-flops that
// build the complementary, dead-timed hs/ls.  See clb/clb_halfbridge.v / readme.
#define CLB_CLK_SEL   0x05                 // CLBCLK = FOSC (32 MHz) -> BLE_clk; FOSC clocks
                                           // the counter (HFINTOSC 0x06 left it dead).
#define PPS_CLBPPSOUT0 0x24                // RxyPPS: CLBPPSOUT0 (= pwm_out)
#define PPS_CLC1OUT    0x01                // RxyPPS: CLC1OUT (= hs)
#define PPS_CLC2OUT    0x02                // RxyPPS: CLC2OUT (= ls)
#define IN_RC2         0x12                // input-PPS code for RC2 (PORTC=010,pin2=010)
#define CLCSEL_PWM     0                   // CLC data: CLCIN0PPS (<- RC2 = pwm)
#define CLCSEL_T2PS    16                  // CLC data: TMR2_Postscaled_OUT (Table 28-2 [16])

static uint8_t g_clb_on = 0;
static uint8_t g_clb_dt = 3;               // dead-time in TMR2(FOSC) ticks = dt*31.25 ns (0..255)
// Selectable PWM frequency: which CLB counter tap (CLBPPSOUTn) drives RC2.
// 0 = CLBPPSOUT0 = cnt[7] ~125 kHz, 1 = CLBPPSOUT1 = cnt[8] ~62.5 kHz.
static uint8_t g_clb_freq = 1;             // default ~62.5 kHz
static const uint32_t g_clb_freq_hz[2] = { 125000, 62500 };

// Stream the bitstream from program memory into the CLB via the NVM scanner.
static void CLB_Load(void)
{
    uint16_t start = (uint16_t)&start_clb_config;
    uint16_t end   = start + CLB_BITSTREAM_LENGTH - 1u;   // last word (matches clb1.c)

    CLBCONbits.EN = 0;                      // CLB off during load
    SCANHADRH = (uint8_t)(end >> 8);   SCANHADRL = (uint8_t)end;
    SCANLADRH = (uint8_t)(start >> 8); SCANLADRL = (uint8_t)start;

    // The scanner feeds the CRC engine; per DS 19.9 the CRC must be enabled and
    // started (CRCEN, CRCGO) BEFORE SGO. Otherwise SCANCON0.DABORT (reset = 1)
    // stays set and the scan aborts immediately -> the bitstream never loads and
    // every CLBPPSOUT reads static high.
    CRCCON0bits.EN  = 1;                    // release CRC from reset
    CRCCON0bits.GO  = 1;                    // start the CRC serial shifter
    SCANCON0bits.EN  = 1;
    SCANDPSbits.DPS  = 1;                   // route scanner data -> CLB
    SCANCON0bits.MD  = 0b01;                // Burst mode: CPU stalls, scan runs to completion
    SCANCON0bits.SGO = 1;                   // start the load (CPU stalls in burst mode)
    while (SCANCON0bits.BUSY) { }
    SCANDPSbits.DPS  = 0;
    SCANCON0bits.SGO = 0;
    SCANCON0bits.EN  = 0;
    CRCCON0bits.GO  = 0;
    CRCCON0bits.EN  = 0;
}

// Dead-time = T2PR ticks of the TMR2 FOSC clock (31.25 ns each). Set live.
static void CLB_SetDeadtime(uint8_t dt)
{
    g_clb_dt = dt;
    T2PR = dt;                              // TMR2 monostable period = dead-time
}

// Select the PWM frequency by routing the chosen CLB counter tap onto RC2.
// f=0 -> CLBPPSOUT0 (cnt[7], ~125 kHz), f=1 -> CLBPPSOUT1 (cnt[8], ~62.5 kHz).
// Live-switchable (TMR2/CLC follow whatever pwm RC2 carries).
static void CLB_SetFreq(uint8_t f)
{
    if (f > 1) f = 1;
    g_clb_freq = f;
    if (g_clb_on) RC2PPS = (uint8_t)(0x24u + f);   // CLBPPSOUT0/1 -> RC2
}

static void CLB_SetEnabled(uint8_t on)
{
    if (on) {
        // Clear the Peripheral Module Disable bits the chain needs (MCC does this
        // in its init; bare-metal must too, or the modules stay held disabled).
        PMD0bits.NVMMD  = 0;                // NVM (scanner reads program memory)
        PMD0bits.CRCMD  = 0;                // CRC / scanner engine
        PMD0bits.SCANMD = 0;                // memory scanner
        PMD4bits.CLBMD  = 0;                // CLB peripheral

        // ---- CLB: free-running counter -> pwm (~62.5 kHz) on CLBPPSOUT0/RC2 ----
        CLBCON = 0x00;                      // disable during load (matches clb1.c order)
        CLB_Load();
        CLBCLK = CLB_CLK_SEL;               // BLE_clk = FOSC
        CLBPPSCON1 = 0x00; CLBPPSCON2 = 0x00; CLBPPSCON3 = 0x00; CLBPPSCON4 = 0x00;
        CLBCONbits.EN = 1;                  // run the counter
        ANSELCbits.ANSELC2 = 0; TRISCbits.TRISC2 = 0;
        RC2PPS = (uint8_t)(0x24u + g_clb_freq);   // RC2 <- selected pwm tap (CLBPPSOUT0/1)

        // ---- TMR2: HLT edge-triggered monostable, retriggered by each pwm edge ----
        // Counts dt FOSC ticks after every edge, then emits TMR2_postscaled.
        T2CON    = 0x00;                    // off; CKPS=000 (prescaler 1:1) -- IMPORTANT:
                                            // clears any prescaler left by a prior `pulse freq`,
                                            // so dead-time = dt x 31.25 ns regardless of history.
        T2INPPS  = IN_RC2;                  // TMR2 external-reset input <- RC2 (pwm)
        T2CLKCON = 0x02;                    // clock = FOSC (32 MHz)
        T2RST    = 0x00;                    // reset source = pin selected by T2INPPS
        T2HLT    = 0x13;                    // MODE = 10011: edge-triggered monostable (any edge)
        T2PR     = g_clb_dt;               // dead-time
        T2CON    = 0x80;                    // ON=1, prescaler 1:1 (1 tick = 31.25 ns)

        // ---- two CLC D-flip-flops build the complementary, dead-timed hs/ls ----
        // Both: data1(d1)=pwm (CLCIN0PPS<-RC2), data2(d2)=TMR2_postscaled.
        // Gate map (standard PIC16 CLC, VERIFY vs Fig 28-3): g1=CLK, g2=D, g3=R.
        //   hs: D=pwm,  CLK=postscaled, R=~pwm  (set dt after a rising edge, clear when pwm low)
        //   ls: D=~pwm, CLK=postscaled, R=pwm
        // hs=1 needs pwm=1 and ls=1 needs pwm=0 -> never both on (non-overlap).
        PMD2bits.CLC1MD = 0; PMD2bits.CLC2MD = 0;   // enable CLC1/CLC2 (PMD2)
        PMD1bits.TMR2MD = 0;                         // enable TMR2 (PMD1)
        CLCIN0PPS = IN_RC2;
        // This family uses the CLCSELECT indirection: write CLCSELECT to pick the
        // instance, then the shared CLCnCON/CLCnSEL/CLCnGLS/CLCnPOL apply to it.
        CLCSELECT = 0x00;                   // ---- CLC1 = hs ----
        CLCnCON = 0x00;
        CLCnSEL0 = CLCSEL_PWM; CLCnSEL1 = CLCSEL_T2PS; CLCnSEL2 = 0; CLCnSEL3 = 0;
        CLCnGLS0 = 0x08;                    // g1(CLK) = d2 true  (postscaled)
        CLCnGLS1 = 0x02;                    // g2(D)   = d1 true  (pwm)
        CLCnGLS2 = 0x01;                    // g3(R)   = d1 neg   (~pwm)
        CLCnGLS3 = 0x00;
        CLCnPOL  = 0x00;
        CLCnCON  = 0x85;                    // EN=1, MODE=101 (2-input D-FF with Reset)
        CLCSELECT = 0x01;                   // ---- CLC2 = ls ----
        CLCnCON = 0x00;
        CLCnSEL0 = CLCSEL_PWM; CLCnSEL1 = CLCSEL_T2PS; CLCnSEL2 = 0; CLCnSEL3 = 0;
        CLCnGLS0 = 0x08;                    // g1(CLK) = d2 true  (postscaled)
        CLCnGLS1 = 0x01;                    // g2(D)   = d1 neg   (~pwm)
        CLCnGLS2 = 0x02;                    // g3(R)   = d1 true  (pwm)
        CLCnGLS3 = 0x00;
        CLCnPOL  = 0x00;
        CLCnCON  = 0x85;

        RC0PPS = PPS_CLC1OUT;               // RC0 <- hs (CLC1OUT)
        RC1PPS = PPS_CLC2OUT;               // RC1 <- ls (CLC2OUT)
    } else {
        CLBCONbits.EN = 0;
        T2CONbits.ON = 0; T2HLT = 0x00; T2RST = 0x00; T2CLKCON = 0x01; // TMR2 back to PWM base
        CLCSELECT = 0x00; CLCnCON = 0x00;  CLCSELECT = 0x01; CLCnCON = 0x00;
        RC0PPS = 0x2C;                      // RC0 -> PWM1 again
        RC1PPS = 0x2D;                      // RC1 -> PWM2 again
    }
    g_clb_on = on;
}

// ===== Generic CLB fixture (CLB capability suite, clb_analyze.py) =====
// Loads whatever bitstream is compiled in and exposes its four external outputs
// CLBPPSOUT0..3 on RC0..RC3 (the four Saleae channels) with NO half-bridge logic.
// `clbsw` drives the 32-bit software input (CLBSWIN) so combinational/logic designs
// can be exercised from the CLI without spending a pin on a stimulus.
// mode: 0 = off, 1 = "on" (4 outputs OUT0..3 -> RC0..3),
//       2 = "in" (3 outputs OUT0..2 -> RC0..2; RC3 = PWM1 input fed to CLBIN0PPS).
static void CLBraw_Enable(uint8_t mode)
{
    if (mode) {
        PMD0bits.NVMMD = 0; PMD0bits.CRCMD = 0; PMD0bits.SCANMD = 0;
        PMD4bits.CLBMD = 0;
        CLBCON = 0x00;
        CLB_Load();
        CLBCLK = (mode == 3) ? 0x01 : CLB_CLK_SEL;  // mode 3: BLE_clk = CLBIN0PPS pin; else FOSC
        CLBPPSCON1 = 0x00; CLBPPSCON2 = 0x00; CLBPPSCON3 = 0x00; CLBPPSCON4 = 0x00;
        CLBCONbits.EN = 1;
        ANSELCbits.ANSELC0 = 0; ANSELCbits.ANSELC1 = 0;
        ANSELCbits.ANSELC2 = 0; ANSELCbits.ANSELC3 = 0;
        TRISCbits.TRISC0 = 0; TRISCbits.TRISC1 = 0;
        TRISCbits.TRISC2 = 0; TRISCbits.TRISC3 = 0;
        RC0PPS = 0x24; RC1PPS = 0x25;       // CLBPPSOUT0 -> RC0, OUT1 -> RC1
        if (mode == 2 || mode == 3) {
            RC2PPS = 0x26;                  // CLBPPSOUT2 -> RC2 (3rd output)
            RC3PPS = 0x2C;                  // RC3 <- PWM1 (the observable input stimulus)
            CLBIN0PPS = 0x13;               // CLB IN0 / clock reads pin RC3
            PWM1CONbits.EN = 1;             // ensure the stimulus PWM is running
        } else {
            RC2PPS = 0x26; RC3PPS = 0x27;   // CLBPPSOUT2 -> RC2, OUT3 -> RC3
        }
    } else {
        CLBCONbits.EN = 0;
        RC0PPS = 0x2C; RC1PPS = 0x2D;       // RC0/RC1 back to PWM1/PWM2
        RC2PPS = 0x00; RC3PPS = 0x00;       // RC2/RC3 back to port latch
    }
}

// Write the 32-bit CLB software input. Per DS 29.4.1 the U/H/M bytes must be
// written before CLBSWINL; writing CLBSWINL latches all four into the fabric.
static void CLB_SetSwin(uint32_t v)
{
    while (CLBCONbits.BUSY) { }          // wait for any prior transfer to finish
    CLBSWINU = (uint8_t)(v >> 24);       // U/H/M must be written BEFORE L (DS 29.4.1)
    CLBSWINH = (uint8_t)(v >> 16);
    CLBSWINM = (uint8_t)(v >> 8);
    CLBSWINL = (uint8_t)v;               // writing L latches all four -> transfer starts
    while (CLBCONbits.BUSY) { }          // wait until the 32-bit transfer completes
}

// ============================= UART I/O ==============================
static void UART1_Write(uint8_t b)
{
    while (!PIR4bits.TX1IF) { }         // wait until TX1REG is empty
    TX1REG = b;
}

// Minimal UART output helpers (replace printf to keep the heavy stdio engine
// and its long-formatting out of the program memory).
static void uputc(char c)               // write one character
{
    UART1_Write((uint8_t)c);
}

static void uputs(const char *s)        // write a string
{
    while (*s) UART1_Write((uint8_t)*s++);
}

static void uput_ul(uint32_t v)         // write an unsigned long as decimal
{
    char b[10];
    uint8_t i = 0;
    if (v == 0) { UART1_Write('0'); return; }
    while (v) { b[i++] = (char)('0' + v % 10u); v /= 10u; }
    while (i) UART1_Write((uint8_t)b[--i]);
}

static void uput_milli(uint32_t m)      // write a milli-unit value as "x.xxx"
{
    uint32_t f = m % 1000u;
    uput_ul(m / 1000u);
    UART1_Write('.');
    UART1_Write((uint8_t)('0' + f / 100u));
    UART1_Write((uint8_t)('0' + (f / 10u) % 10u));
    UART1_Write((uint8_t)('0' + f % 10u));
}

// non-blocking: returns 1 and stores the byte in *c if one is available
static uint8_t UART1_TryRead(uint8_t *c)
{
    if (RC1STAbits.OERR) {              // clear overrun error
        RC1STAbits.CREN = 0;
        RC1STAbits.CREN = 1;
    }
    if (!PIR4bits.RC1IF) {
        return 0;
    }
    *c = RC1REG;
    return 1;
}

// ============================= Commands ==============================
static void cmd_help(void)
{
    uputs("\r\nCommands:\r\n");
    uputs("  help | version | reset\r\n");
    uputs("  pulse freq <Hz> | a|b on|off | a|b duty <pct> | status\r\n");
    uputs("  clb on|off | dt <0-255> | freq <0-1> | status   (HB: adj dead-time, 2 freqs)\r\n");
    uputs("  pinid   (GPIO-toggle RC0..RC3 1x/2x/3x/4x -> verify Saleae wiring)\r\n");
    uputs("  clbraw on|off | clbsw <hex>   (generic CLB fixture: OUT0..3->RC0..3)\r\n");
}

static void cmd_version(void)
{
    uputs(FW_BANNER); uputs("\r\n");
}

static void cmd_reset(void)
{
    uputs("Resetting...\r\n");
    while (!TX1STAbits.TRMT) { }         // wait until everything is sent
    asm("reset");                        // PIC16 RESET instruction
}

static void cmd_pulse(char *a1, char *a2, char *a3)
{
    if (a1 && strcmp(a1, "status") == 0) {
        uputs("Frequency = "); uput_milli(pwm_actual_mfreq()); uputs(" Hz (shared)\r\n");
        uputs("A (RC0): "); uputs(g_enA ? "ON" : "OFF"); uputs(", duty ");
        uput_milli(pwm_actual_mpct(g_dcA)); uputs(" %\r\n");
        uputs("B (RC1): "); uputs(g_enB ? "ON" : "OFF"); uputs(", duty ");
        uput_milli(pwm_actual_mpct(g_dcB)); uputs(" %\r\n");
        return;
    }
    if (a1 && a2 && strcmp(a1, "freq") == 0) {
        uint32_t f;
        if (!parse_u32(a2, &f)) {
            uputs("Error: invalid number '"); uputs(a2); uputs("'\r\n");
        } else if (PWM_SetFrequency(f)) {
            uputs("Frequency -> "); uput_milli(pwm_actual_mfreq());
            uputs(" Hz (requested "); uputs(a2); uputs(")\r\n");
        } else {
            uputs("Error: frequency out of range (~244 Hz .. 4 MHz)\r\n");
        }
        return;
    }
    if (a1 && a2 && a1[1] == '\0' && (a1[0] == 'a' || a1[0] == 'b')) {
        char ch = a1[0];
        char up = (ch == 'a') ? 'A' : 'B';
        if (strcmp(a2, "on")  == 0) { PWM_Enable(ch, 1); uputs("Signal "); uputc(up); uputs(" -> ON\r\n");  return; }
        if (strcmp(a2, "off") == 0) { PWM_Enable(ch, 0); uputs("Signal "); uputc(up); uputs(" -> OFF\r\n"); return; }
        if (strcmp(a2, "duty") == 0 && a3) {
            uint32_t mpct;
            if (!parse_milli(a3, &mpct)) {
                uputs("Error: invalid number '"); uputs(a3); uputs("'\r\n");
                return;
            }
            PWM_SetDuty(ch, mpct);
            uputs("Duty "); uputc(up); uputs(" -> ");
            uput_milli(pwm_actual_mpct(ch == 'a' ? g_dcA : g_dcB));
            uputs(" % (requested "); uputs(a3); uputs(")\r\n");
            return;
        }
    }
    uputs("Error: pulse freq <Hz> | a|b on|off | a|b duty <0-100> | status\r\n");
}

static void cmd_clb(char *a1, char *a2)
{
    if (a1 && strcmp(a1, "on") == 0) {
        CLB_SetEnabled(1);
        uputs("CLB half-bridge -> ON (RC0=HS, RC1=LS; CLB-generated PWM)\r\n");
    } else if (a1 && strcmp(a1, "off") == 0) {
        CLB_SetEnabled(0);
        uputs("CLB half-bridge -> OFF (RC0/RC1 back to PWM)\r\n");
    } else if (a1 && a2 && strcmp(a1, "dt") == 0) {
        uint32_t v;
        if (!parse_u32(a2, &v)) { uputs("Error: invalid number '"); uputs(a2); uputs("'\r\n"); return; }
        if (v > 255) v = 255;
        CLB_SetDeadtime((uint8_t)v);
        uputs("Dead-time -> "); uput_ul(v); uputs(" ticks (~");
        uput_ul((uint32_t)v * 3125u / 100u); uputs(" ns)\r\n");
    } else if (a1 && a2 && strcmp(a1, "freq") == 0) {
        uint32_t v;
        if (!parse_u32(a2, &v)) { uputs("Error: invalid number '"); uputs(a2); uputs("'\r\n"); return; }
        if (v > 1) { uputs("Error: freq must be 0 (~125 kHz) or 1 (~62.5 kHz)\r\n"); return; }
        CLB_SetFreq((uint8_t)v);
        uputs("PWM freq -> "); uput_ul(g_clb_freq_hz[g_clb_freq]); uputs(" Hz\r\n");
    } else if (a1 && strcmp(a1, "status") == 0) {
        uputs("CLB: "); uputs(g_clb_on ? "ON" : "OFF");
        uputs(", dead-time "); uput_ul(g_clb_dt); uputs(" ticks (~");
        uput_ul((uint32_t)g_clb_dt * 3125u / 100u); uputs(" ns), PWM ~");
        uput_ul(g_clb_freq_hz[g_clb_freq]); uputs(" Hz\r\n");
    } else {
        uputs("Error: clb on|off | dt <0-255> | freq <0-1> | status\r\n");
    }
}

// ===================== Pin-identification test =======================
// Drive RC0..RC3 as plain GPIO and blink each a UNIQUE number of times
// (RC0=1x, RC1=2x, RC2=3x, RC3=4x). On the Saleae, channel Dn must then
// show (n+1) pulses -> confirms the probe wiring RC0->D0 .. RC3->D3.
static void cmd_pinid(void)
{
    RC0PPS = 0; RC1PPS = 0; RC2PPS = 0; RC3PPS = 0;   // 0 = driven by port latch
    ANSELCbits.ANSELC0 = 0; ANSELCbits.ANSELC1 = 0;
    ANSELCbits.ANSELC2 = 0; ANSELCbits.ANSELC3 = 0;
    TRISCbits.TRISC0 = 0; TRISCbits.TRISC1 = 0;
    TRISCbits.TRISC2 = 0; TRISCbits.TRISC3 = 0;
    LATC &= 0xF0u;
    uputs("pinid: RC0=1 RC1=2 RC2=3 RC3=4 pulses (~2.3s)\r\n");
    for (uint8_t frame = 0; frame < 10u; frame++) {
        for (uint8_t pin = 0; pin < 4u; pin++) {
            uint8_t mask = (uint8_t)(1u << pin);
            for (uint8_t n = 0; n <= pin; n++) {       // pin+1 pulses
                LATC |= mask;   __delay_ms(5);
                LATC &= 0xF0u;  __delay_ms(5);
            }
            __delay_ms(20);                            // gap between pins
        }
        __delay_ms(50);                                // gap between frames
    }
    LATC &= 0xF0u;
}

// =========================== Line parser =============================
static void process_line(char *line)
{
    char *cmd = strtok(line, " ");
    if (cmd == NULL) {
        return;                          // empty line
    }
    if (strcmp(cmd, "help") == 0) {
        cmd_help();
    } else if (strcmp(cmd, "version") == 0) {
        cmd_version();
    } else if (strcmp(cmd, "reset") == 0) {
        cmd_reset();
    } else if (strcmp(cmd, "pulse") == 0) {
        char *a1 = strtok(NULL, " ");
        char *a2 = strtok(NULL, " ");
        char *a3 = strtok(NULL, " ");
        cmd_pulse(a1, a2, a3);
    } else if (strcmp(cmd, "clb") == 0) {
        char *a1 = strtok(NULL, " ");
        char *a2 = strtok(NULL, " ");
        cmd_clb(a1, a2);
    } else if (strcmp(cmd, "pinid") == 0) {
        cmd_pinid();
    } else if (strcmp(cmd, "clbraw") == 0) {
        char *a1 = strtok(NULL, " ");
        if (a1 && strcmp(a1, "on") == 0)       { CLBraw_Enable(1); uputs("CLBRAW -> ON (OUT0..3 -> RC0..3)\r\n"); }
        else if (a1 && strcmp(a1, "in") == 0)  { CLBraw_Enable(2); uputs("CLBRAW -> IN (OUT0..2 -> RC0..2, RC3=PWM1->IN0)\r\n"); }
        else if (a1 && strcmp(a1, "ck") == 0)  { CLBraw_Enable(3); uputs("CLBRAW -> CK (BLE_clk = CLBIN0PPS pin RC3)\r\n"); }
        else if (a1 && strcmp(a1, "off") == 0) { CLBraw_Enable(0); uputs("CLBRAW -> OFF\r\n"); }
        else uputs("Error: clbraw on|in|off\r\n");
    } else if (strcmp(cmd, "clbsw") == 0) {
        char *a1 = strtok(NULL, " ");
        uint32_t v;
        if (a1 && parse_hex(a1, &v)) { CLB_SetSwin(v); uputs("CLBSWIN set\r\n"); }
        else uputs("Error: clbsw <hex>\r\n");
    } else if (strcmp(cmd, "clbck") == 0) {        // set CLB clock source (Table 29-4) at run time
        char *a1 = strtok(NULL, " ");
        uint32_t v;
        if (a1 && parse_hex(a1, &v)) {
            OSCENbits.MFOEN = 1;                   // make MFINTOSC available (harmless if unused)
            CLBCONbits.EN = 0; CLBCLK = (uint8_t)v; CLBCONbits.EN = 1;
            uputs("CLBCLK set\r\n");
        } else uputs("Error: clbck <hex>\r\n");
    } else {
        uputs("Unknown command: '"); uputs(cmd); uputs("'  (type 'help')\r\n");
    }
}

// =================== Console line editor + history ===================
// A small readline-style editor: left/right move the cursor, characters are
// inserted at the cursor, Backspace/Del remove, and Up/Down recall the last
// HIST_DEPTH commands. Arrow keys arrive as ANSI sequences (ESC [ A/B/C/D).
#define CMD_BUF_LEN 48
#define HIST_DEPTH  10

static char     cmdBuf[CMD_BUF_LEN];     // current line
static uint8_t  cmdLen = 0;              // characters in cmdBuf
static uint8_t  cmdPos = 0;              // cursor position (0..cmdLen)

static char     histBuf[HIST_DEPTH][CMD_BUF_LEN];  // [0] = most recent
static uint8_t  histCount = 0;           // valid history entries
static int      histNav = -1;            // -1 = live line, else history index
static char     liveBuf[CMD_BUF_LEN];    // live line saved while browsing

static uint8_t  escState = 0;            // 0 normal, 1 after ESC, 2 after ESC[
static uint16_t escParam = 0;            // numeric parameter of CSI sequence

// Reprint the whole line ("> " + buffer), erase leftovers, position cursor.
static void redraw_line(void)
{
    UART1_Write('\r');
    UART1_Write('>'); UART1_Write(' ');
    for (uint8_t i = 0; i < cmdLen; i++) UART1_Write((uint8_t)cmdBuf[i]);
    uputs("\x1b[K");                               // erase to end of line
    if (cmdLen > cmdPos) { uputs("\x1b["); uput_ul((uint32_t)(cmdLen - cmdPos)); uputc('D'); }
}

static void load_line(const char *src)
{
    cmdLen = 0;
    while (src[cmdLen] && cmdLen < CMD_BUF_LEN - 1) { cmdBuf[cmdLen] = src[cmdLen]; cmdLen++; }
    cmdPos = cmdLen;
    redraw_line();
}

static void hist_push(const char *line)
{
    if (line[0] == '\0') return;                   // never store empty lines
    if (histCount > 0 && strcmp(histBuf[0], line) == 0) return;  // skip dup
    for (int i = HIST_DEPTH - 1; i > 0; i--)       // shift older entries down
        memcpy(histBuf[i], histBuf[i - 1], CMD_BUF_LEN);
    uint8_t i = 0;
    for (; line[i] && i < CMD_BUF_LEN - 1; i++) histBuf[0][i] = line[i];
    histBuf[0][i] = '\0';
    if (histCount < HIST_DEPTH) histCount++;
}

static void hist_up(void)
{
    if (histNav + 1 >= (int)histCount) return;     // already at the oldest
    if (histNav == -1) {                           // entering history: save live line
        cmdBuf[cmdLen] = '\0';
        memcpy(liveBuf, cmdBuf, CMD_BUF_LEN);
    }
    histNav++;
    load_line(histBuf[histNav]);
}

static void hist_down(void)
{
    if (histNav < 0) return;                        // already on the live line
    histNav--;
    load_line(histNav < 0 ? liveBuf : histBuf[histNav]);
}

static void insert_char(uint8_t ch)
{
    if (cmdLen >= CMD_BUF_LEN - 1) return;
    if (cmdPos == cmdLen) {            // append at end: cheap single-char echo
        cmdBuf[cmdLen++] = (char)ch;   // (a full redraw per key would tie up the
        cmdPos++;                      //  TX long enough to drop incoming RX bytes
        UART1_Write(ch);               //  when a host streams a command fast)
        return;
    }
    for (uint8_t i = cmdLen; i > cmdPos; i--) cmdBuf[i] = cmdBuf[i - 1];  // mid-line
    cmdBuf[cmdPos] = (char)ch;
    cmdLen++; cmdPos++;
    redraw_line();
}

static void backspace(void)                         // remove char left of cursor
{
    if (cmdPos == 0) return;
    for (uint8_t i = cmdPos - 1; i < cmdLen - 1; i++) cmdBuf[i] = cmdBuf[i + 1];
    cmdLen--; cmdPos--;
    redraw_line();
}

static void delete_at(void)                         // remove char at cursor (Del)
{
    if (cmdPos >= cmdLen) return;
    for (uint8_t i = cmdPos; i < cmdLen - 1; i++) cmdBuf[i] = cmdBuf[i + 1];
    cmdLen--;
    redraw_line();
}

static void console_feed(uint8_t c)
{
    // ---- ANSI escape-sequence parser (arrow / Home / End / Del) ----
    if (escState == 1) {                            // after ESC
        escState = (c == '[' || c == 'O') ? 2 : 0;
        escParam = 0;
        return;
    }
    if (escState == 2) {                            // after ESC[ (CSI)
        if (c >= '0' && c <= '9') { escParam = escParam * 10u + (uint16_t)(c - '0'); return; }
        if (c == ';') return;                       // ignore parameter separators
        escState = 0;
        switch (c) {
            case 'A': hist_up();      break;        // Up
            case 'B': hist_down();    break;        // Down
            case 'C': if (cmdPos < cmdLen) { cmdPos++; uputs("\x1b[C"); } break;  // Right
            case 'D': if (cmdPos > 0)      { cmdPos--; uputs("\x1b[D"); } break;  // Left
            case 'H': cmdPos = 0;      redraw_line(); break;     // Home
            case 'F': cmdPos = cmdLen; redraw_line(); break;     // End
            case '~':
                if      (escParam == 3) delete_at();
                else if (escParam == 1 || escParam == 7) { cmdPos = 0;      redraw_line(); }
                else if (escParam == 4 || escParam == 8) { cmdPos = cmdLen; redraw_line(); }
                break;
            default: break;
        }
        return;
    }
    if (c == 0x1B) { escState = 1; return; }        // ESC starts a sequence

    // ---- normal keys ----
    if (c == '\r' || c == '\n') {
        UART1_Write('\r'); UART1_Write('\n');
        cmdBuf[cmdLen] = '\0';
        hist_push(cmdBuf);
        histNav = -1;
        process_line(cmdBuf);
        cmdLen = 0; cmdPos = 0;
        uputs("> ");
    } else if (c == 0x08 || c == 0x7F) {            // Backspace
        backspace();
    } else if (c >= 0x20 && c < 0x7F) {             // printable -> insert at cursor
        insert_char(c);
    }
}

// =============================== main ================================
int main(void)
{
    OSCFRQbits.FRQ = 0b101;             // 32 MHz (redundant with RSTOSC)

    UART1_Init();
    PWM_Init();

    uputs("\r\n"); uputs(FW_BANNER); uputs("\r\n");
    uputs("UART console ready (115200 8N1)\r\n");
    cmd_help();
    uputs("> ");

    uint8_t c;
    while (1) {
        if (UART1_TryRead(&c)) {
            console_feed(c);
        }
    }
}
