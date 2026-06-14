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
#include <stdio.h>
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

// Print a milli-unit value (x1000) as "x.xxx".
static void print_milli(uint32_t m)
{
    printf("%lu.%03lu", (unsigned long)(m / 1000u), (unsigned long)(m % 1000u));
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

// ============================= UART I/O ==============================
static void UART1_Write(uint8_t b)
{
    while (!PIR4bits.TX1IF) { }         // wait until TX1REG is empty
    TX1REG = b;
}

// printf() redirection to the UART (XC8 hook)
void putch(char c)
{
    UART1_Write((uint8_t)c);
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
    printf("\r\nCommands:\r\n");
    printf("  help                  - show this help\r\n");
    printf("  version               - show firmware build timestamp\r\n");
    printf("  reset                 - software reset (restart)\r\n");
    printf("  pulse freq <Hz>       - set shared PWM frequency (244 Hz..4 MHz)\r\n");
    printf("  pulse a|b on|off      - enable/disable channel (RC0/RC1)\r\n");
    printf("  pulse a|b duty <0-100>- set channel duty cycle (percent, e.g. 33.3)\r\n");
    printf("  pulse status          - show current state\r\n");
    printf("\r\nPWM: both channels share one frequency (Timer2 base).\r\n");
    printf("     Full 10-bit duty up to 31.25 kHz, coarser above.\r\n");
}

static void cmd_version(void)
{
    printf("%s\r\n", FW_BANNER);
}

static void cmd_reset(void)
{
    printf("Resetting...\r\n");
    while (!TX1STAbits.TRMT) { }         // wait until everything is sent
    asm("reset");                        // PIC16 RESET instruction
}

static void cmd_pulse(char *a1, char *a2, char *a3)
{
    if (a1 && strcmp(a1, "status") == 0) {
        printf("Frequency = "); print_milli(pwm_actual_mfreq()); printf(" Hz (shared)\r\n");
        printf("A (RC0): %s, duty ", g_enA ? "ON" : "OFF");
        print_milli(pwm_actual_mpct(g_dcA)); printf(" %%\r\n");
        printf("B (RC1): %s, duty ", g_enB ? "ON" : "OFF");
        print_milli(pwm_actual_mpct(g_dcB)); printf(" %%\r\n");
        return;
    }
    if (a1 && a2 && strcmp(a1, "freq") == 0) {
        uint32_t f;
        if (!parse_u32(a2, &f)) {
            printf("Error: invalid number '%s'\r\n", a2);
        } else if (PWM_SetFrequency(f)) {
            printf("Frequency -> "); print_milli(pwm_actual_mfreq());
            printf(" Hz (requested %s)\r\n", a2);
        } else {
            printf("Error: frequency out of range (~244 Hz .. 4 MHz)\r\n");
        }
        return;
    }
    if (a1 && a2 && a1[1] == '\0' && (a1[0] == 'a' || a1[0] == 'b')) {
        char ch = a1[0];
        char up = (ch == 'a') ? 'A' : 'B';
        if (strcmp(a2, "on")  == 0) { PWM_Enable(ch, 1); printf("Signal %c -> ON\r\n",  up); return; }
        if (strcmp(a2, "off") == 0) { PWM_Enable(ch, 0); printf("Signal %c -> OFF\r\n", up); return; }
        if (strcmp(a2, "duty") == 0 && a3) {
            uint32_t mpct;
            if (!parse_milli(a3, &mpct)) {
                printf("Error: invalid number '%s'\r\n", a3);
                return;
            }
            PWM_SetDuty(ch, mpct);
            printf("Duty %c -> ", up);
            print_milli(pwm_actual_mpct(ch == 'a' ? g_dcA : g_dcB));
            printf(" %% (requested %s)\r\n", a3);
            return;
        }
    }
    printf("Error: pulse freq <Hz> | a|b on|off | a|b duty <0-100> | status\r\n");
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
    } else {
        printf("Unknown command: '%s'  (type 'help')\r\n", cmd);
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
    printf("\x1b[K");                              // erase to end of line
    if (cmdLen > cmdPos) printf("\x1b[%uD", (unsigned)(cmdLen - cmdPos));
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
            case 'C': if (cmdPos < cmdLen) { cmdPos++; printf("\x1b[C"); } break;  // Right
            case 'D': if (cmdPos > 0)      { cmdPos--; printf("\x1b[D"); } break;  // Left
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
        printf("> ");
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

    printf("\r\n%s\r\n", FW_BANNER);
    printf("UART console ready (115200 8N1)\r\n");
    cmd_help();
    printf("> ");

    uint8_t c;
    while (1) {
        if (UART1_TryRead(&c)) {
            console_feed(c);
        }
    }
}
