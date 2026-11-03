`timescale 1ns/1ps
module gwx_instrument_top #(
 parameter CPB=234,ROM_FILE="rom_banks/",MODEL_PREFIX="rom_banks/",HAS_EXTERNAL=0,
 parameter ENABLE_FORWARD=1,ENABLE_PREDICT=1,RANDOM_WAIT=0
)(input wire clk,rst_n,uart_rx,input wire[7:0]signal_in,
 output wire uart_tx,output wire[3:0]led,
 output wire finished,halted,output wire[31:0]exit_code,output wire[3:0]cause);
 reg[1:0]reset_release;
 always @(posedge clk or negedge rst_n)
  if(!rst_n)reset_release<=0;else reset_release<={reset_release[0],1'b1};
 wire[31:0]gpio;
 assign led=gpio[3:0];
 gwx_external_soc #(.CPB(CPB),.ROM_FILE(ROM_FILE),.MODEL_PREFIX(MODEL_PREFIX),.HAS_EXTERNAL(HAS_EXTERNAL),
  .ENABLE_FORWARD(ENABLE_FORWARD),.ENABLE_PREDICT(ENABLE_PREDICT),.RANDOM_WAIT(RANDOM_WAIT))soc(
  .clk(clk),.rst_n(reset_release[1]),.rx(uart_rx),.signal_in(signal_in),.tx(uart_tx),
  .gpio_out(gpio),.finished(finished),.halted(halted),.exit_code(exit_code),.cause(cause));
endmodule
