(* syscfg.CLKDIV = 3'd0 *)
module counter_3tap (CLK, o0, o1, o2);
    input CLK; output o0, o1, o2;
    reg [9:0] cnt = 0;
    always @(posedge CLK) cnt <= cnt + 1;
    assign o0 = cnt[7];   // 125 kHz
    assign o1 = cnt[8];   // 62.5 kHz
    assign o2 = cnt[9];   // 31.25 kHz
endmodule
