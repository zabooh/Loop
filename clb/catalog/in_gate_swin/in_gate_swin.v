(* syscfg.CLKDIV = 3'd0 *)
module in_gate_swin (CLK, IN0, CLBSWIN0, o0, o1);
    (* pincfg.IN0.mux = 7'd0 *) (* pincfg.IN0.syncmode.sync *)
    input CLK, IN0, CLBSWIN0; output o0, o1;
    reg r0=0, r1=0;
    always @(posedge CLK) begin r0 <= IN0 & CLBSWIN0; r1 <= IN0; end
    assign o0=r0; assign o1=r1;   // o0 = PWM gated by sw0; o1 = PWM reference
endmodule
