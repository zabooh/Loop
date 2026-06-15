(* syscfg.CLKDIV = 3'd0 *)
module swin_reg (CLK, CLBSWIN0, CLBSWIN1, CLBSWIN2, CLBSWIN3, o0, o1, o2, o3);
    input CLK, CLBSWIN0, CLBSWIN1, CLBSWIN2, CLBSWIN3; output o0, o1, o2, o3;
    reg r0=0, r1=0, r2=0, r3=0;
    always @(posedge CLK) begin
        r0 <= CLBSWIN0; r1 <= CLBSWIN1; r2 <= CLBSWIN2; r3 <= CLBSWIN3;
    end
    assign o0=r0; assign o1=r1; assign o2=r2; assign o3=r3;
endmodule
