`timescale 1ns/1ps
module guanweixin_ai_board_top(input wire clk,rst_n,uart_rx,input wire[7:0]signal_in,output wire uart_tx,output wire[3:0]led);
 wire [179:0] probe_bus;
 reg [179:0] debug_probe /* synthesis syn_preserve=1 syn_noprune=1 syn_keep=1 */;
 always @(posedge clk) if(!rst_n)debug_probe<=0;else debug_probe<=probe_bus;
 gwx_instrument_top #(.CPB(234),.HAS_EXTERNAL(1),.ROM_FILE("rom_banks/"),
 .MODEL_PREFIX("rom_banks/"))application(
 .probe_bus(probe_bus),.clk(clk),.rst_n(rst_n),.uart_rx(uart_rx),.signal_in(signal_in),.uart_tx(uart_tx),.led(led),
 .finished(),.halted(),.exit_code(),.cause());
endmodule
