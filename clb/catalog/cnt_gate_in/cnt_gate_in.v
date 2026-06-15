(* syscfg.CLKDIV = 3'd0 *)
module cnt_gate_in (CLK, IN0, o0, o1);
    (* pincfg.IN0.mux = 7'd0 *) (* pincfg.IN0.syncmode.sync *)
    input CLK, IN0; output o0, o1;
    reg [8:0] cnt = 0; reg r0=0, r1=0;
    always @(posedge CLK) begin
        cnt <= cnt + 1;
        r0 <= cnt[7] & IN0;        // counter gated by pin input
        r1 <= cnt[7];              // raw counter reference
    end
    assign o0=r0; assign o1=r1;
endmodule
