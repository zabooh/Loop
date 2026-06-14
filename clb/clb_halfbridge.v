// =====================================================================
// clb_halfbridge.v  -  complementary half-bridge with RUNTIME dead-time
//
// One PWM input -> two non-overlapping outputs HS (RC0) and LS (RC1).
// The dead-time is *not* fixed in the bitstream: it is taken from a 4-bit
// value `dt` wired to the CLB software-input register CLBSWIN, so the CPU /
// CLI can change it at run time (e.g. `clb dt 3`).
//
// The PIC16F13145 has no CWG, so the CLB is the way to build this.
//
//   dead-time = dt cycles of `clk`   (= dt / F_BLEclk seconds)
//   e.g. F_BLEclk = 8 MHz -> 125 ns/step, dt 0..15 -> 0 .. 1.875 us
//
// How it works: a counter is cleared on every edge of pwm_in and counts up
// to `dt`, then holds. `settled` is high only after dt cycles with no edge,
// so during each transition both outputs are low for dt cycles (the dead-time).
//
//   hs =  pwm_in & settled       (high-side, rising edge delayed by dt)
//   ls = ~pwm_in & settled       (low-side,  falling edge delayed by dt)
//
// Import into the MCC Melody CLB Synthesizer (Verilog input); set this as the
// top module. Map pwm_in to PWM1 (internal), hs->RC0, ls->RC1 via CLB PPS,
// and dt[3:0] to four CLBSWIN bits.
// =====================================================================
module clb_halfbridge (
    input  wire       clk,      // CLB BLE_clk (CLBCLK source + divider)
    input  wire       pwm_in,   // source PWM (PWM1 routed into the CLB)
    input  wire [3:0] dt,       // dead-time in clk cycles, from CLBSWIN
    output wire       hs,       // high-side -> RC0 via CLB PPS
    output wire       ls        // low-side  -> RC1 via CLB PPS
);
    reg       pwm_d = 1'b0;     // previous input sample (edge detect)
    reg [3:0] cnt   = 4'd0;     // cycles since the last input edge

    wire edge_seen = pwm_in ^ pwm_d;

    always @(posedge clk) begin
        pwm_d <= pwm_in;
        if (edge_seen)        cnt <= 4'd0;        // restart on every transition
        else if (cnt != dt)   cnt <= cnt + 4'd1;  // count up to dt, then hold
    end

    wire settled = (cnt == dt);                   // dt cycles elapsed since edge

    assign hs =  pwm_in & settled;
    assign ls = ~pwm_in & settled;
endmodule
