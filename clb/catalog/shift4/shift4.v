(* syscfg.CLKDIV = 3'd0 *)
module shift4 (CLK, IN0, o0, o1);
    (* pincfg.IN0.mux = 7'd0 *) (* pincfg.IN0.syncmode.sync *)
    input CLK, IN0; output o0, o1;
    reg [3:0] sr = 0;
    always @(posedge CLK) sr <= {sr[2:0], IN0};
    assign o0 = sr[0];   // 1-clock delayed
    assign o1 = sr[3];   // 4-clock delayed
endmodule
