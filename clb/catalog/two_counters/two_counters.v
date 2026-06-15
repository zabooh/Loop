(* syscfg.CLKDIV = 3'd0 *)
module two_counters (CLK, o0, o1);
    input CLK; output o0, o1;
    reg [7:0] a = 0; reg [6:0] b = 0;
    always @(posedge CLK) a <= a + 1;
    always @(posedge CLK) b <= b + 1;
    assign o0 = a[7];
    assign o1 = b[6];
endmodule
