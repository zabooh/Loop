(* syscfg.CLKDIV = 3'd0 *)
module cnt_gate_swin (CLK, CLBSWIN0, o0, o1);
    input CLK, CLBSWIN0; output o0, o1;
    reg [8:0] cnt = 0; reg r0=0, r1=0;
    always @(posedge CLK) begin
        cnt <= cnt + 1;
        r0 <= cnt[7] & CLBSWIN0;   // counter gated by software bit
        r1 <= cnt[7];              // raw counter reference
    end
    assign o0=r0; assign o1=r1;
endmodule
