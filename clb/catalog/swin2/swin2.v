(* syscfg.CLKDIV = 3'd0 *)
module swin2 (CLK, CLBSWIN0, CLBSWIN1, o0, o1);
    input CLK, CLBSWIN0, CLBSWIN1; output o0, o1;
    reg r0=0, r1=0;
    always @(posedge CLK) begin r0 <= CLBSWIN0; r1 <= CLBSWIN1; end
    assign o0=r0; assign o1=r1;
endmodule
