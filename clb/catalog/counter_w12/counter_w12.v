(* syscfg.CLKDIV = 3'd0 *)
module counter_w12 (CLK, o0, o1);
    input CLK; output o0, o1;
    reg [11:0] cnt = 0;
    always @(posedge CLK) cnt <= cnt + 1;
    assign o0 = cnt[11];
    assign o1 = cnt[5];
endmodule
