// Self-resetting modulo-5 counter — WORKS on silicon (counter + comparator + sync
// reset + output decode, all internal). Proof that resettable counters are supported;
// only EXTERNAL data inputs are dead (see clb_description.md §10.2). Clock it from a pin
// via `clbraw ck` to measure: outputs = clk/5.
(* syscfg.CLKDIV = 3'd0 *)
module mod5_counter (CLK, o0, o1);
    input CLK; output o0, o1;
    reg [2:0] cnt = 0; reg r0=0, r1=0;
    always @(posedge CLK) begin
        if (cnt == 3'd4) cnt <= 3'd0; else cnt <= cnt + 3'd1;
        r0 <= (cnt == 3'd0);   // clk/5, 20% duty
        r1 <= cnt[1];          // clk/5, 40% duty
    end
    assign o0=r0; assign o1=r1;
endmodule
