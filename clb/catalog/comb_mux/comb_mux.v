(* syscfg.CLKDIV = 3'd0 *)
module comb_mux (CLK, CLBSWIN0, CLBSWIN1, CLBSWIN2, o0, o1);
    input CLK, CLBSWIN0, CLBSWIN1, CLBSWIN2; output o0, o1;
    reg r0=0, r1=0;
    always @(posedge CLK) begin
        r0 <= CLBSWIN2 ? CLBSWIN0 : CLBSWIN1;
        r1 <= CLBSWIN0 & CLBSWIN1 & CLBSWIN2;
    end
    assign o0=r0; assign o1=r1;
endmodule
