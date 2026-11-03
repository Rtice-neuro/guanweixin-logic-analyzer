`timescale 1ns/1ps
module guanweixin_ai_board_top(input wire clk,rst_n,uart_rx,input wire[7:0]signal_in,output wire uart_tx,output wire[3:0]led);
 gwx_instrument_top #(.CPB(234),.HAS_EXTERNAL(1),.ROM_FILE("./rom_banks/"),
 .MODEL_PREFIX("./rom_banks/"))application(
 .clk(clk),.rst_n(rst_n),.uart_rx(uart_rx),.signal_in(signal_in),.uart_tx(uart_tx),.led(led),
 .finished(),.halted(),.exit_code(),.cause());
endmodule
