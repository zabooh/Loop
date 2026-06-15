// =====================================================================
// clb_halfbridge.v  -  CLB PWM GENERATOR with selectable frequency
//
// The CLB does ONLY a free-running counter (the one construct it maps reliably);
// the dead-time is made outside it by TMR2 (HLT monostable) + two CLC D-flip-flops
// (see main.c CLB_SetEnabled and readme_clb.md).
//
// It exposes FOUR octave-spaced frequency taps on CLBPPSOUT0..3. Firmware picks
// which one drives the half-bridge input (RC2) via RC2PPS -> `clb freq 0..3`,
// switchable live without re-synthesis:
//
//   f0 = cnt[7]  -> CLBPPSOUT0 -> BLE_clk/256  ~= 125    kHz
//   f1 = cnt[8]  -> CLBPPSOUT1 -> BLE_clk/512  ~=  62.5  kHz   (default)
//   f2 = cnt[9]  -> CLBPPSOUT2 -> BLE_clk/1024 ~=  31.25 kHz
//   f3 = cnt[10] -> CLBPPSOUT3 -> BLE_clk/2048 ~=  15.625 kHz
//
// BLE_clk = FOSC = 32 MHz (set via CLBCLK). The dead-time (TMR2 on FOSC) is
// independent of this and stays dt x 31.25 ns.
// =====================================================================
(* syscfg.CLKDIV = 3'd0 *)
module clb_halfbridge (CLK, f0, f1);
    input  CLK;                 // CLB BLE_clk (global, 32 MHz, unmapped)
    output f0, f1;              // octave-spaced PWM frequency taps

    reg [8:0] cnt = 9'd0;
    always @(posedge CLK) cnt <= cnt + 9'd1;

    assign f0 = cnt[7];         // ~125   kHz
    assign f1 = cnt[8];         // ~ 62.5 kHz
endmodule
