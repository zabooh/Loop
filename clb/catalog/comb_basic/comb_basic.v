(* syscfg.CLKDIV = 3'd0 *)
module comb_basic (CLK, CLBSWIN0, CLBSWIN1, o0, o1, o2, o3);
    input CLK, CLBSWIN0, CLBSWIN1; output o0, o1, o2, o3;
    reg r0=0, r1=0, r2=0, r3=0;
    always @(posedge CLK) begin
        r0 <= CLBSWIN0 & CLBSWIN1;
        r1 <= CLBSWIN0 | CLBSWIN1;
        r2 <= CLBSWIN0 ^ CLBSWIN1;
        r3 <= ~CLBSWIN0;
    end
    assign o0=r0; assign o1=r1; assign o2=r2; assign o3=r3;
endmodule
