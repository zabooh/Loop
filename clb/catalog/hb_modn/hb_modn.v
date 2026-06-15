// Programmable divider, mod5-style (equality self-reset + toggle), N from CLBSWIN.
(* syscfg.CLKDIV = 3'd0 *)
module hb_modn (CLK, CLBSWIN0, CLBSWIN1, CLBSWIN2, CLBSWIN3, pwm, o1);
    input CLK, CLBSWIN0, CLBSWIN1, CLBSWIN2, CLBSWIN3;
    output pwm, o1;
    wire [3:0] N = {CLBSWIN3, CLBSWIN2, CLBSWIN1, CLBSWIN0};
    reg [3:0] cnt = 4'd0;
    reg pwmr = 1'b0;
    always @(posedge CLK) begin
        if (cnt == N) begin cnt <= 4'd0; pwmr <= ~pwmr; end
        else          cnt <= cnt + 4'd1;
    end
    assign pwm = pwmr;
    assign o1 = cnt[3];
endmodule
