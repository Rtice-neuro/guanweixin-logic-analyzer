`timescale 1ns/1ps
// INTERNAL ONLY: no external header output. 0 normal; 1 missing; 2 early;
// 3 stuck low; 4 stuck high, applied to selected channel. Marker at slot zero.
module gwx_test_source(
 input wire clk,rst_n,restart,armed,input wire [15:0] divider,
 input wire [2:0] mode,channel,output reg [7:0] sample
);
 reg[15:0] ticks;
 reg[6:0] phase;
 reg running;
 reg pulse;
 always @(posedge clk)begin
  if(!rst_n||restart)begin ticks<=0;phase<=0;running<=0;end
  else if(!running)begin ticks<=0;phase<=0;if(armed)running<=1;end
  else if(ticks>=divider-1'b1)begin ticks<=0;phase<=phase==95?0:phase+1'b1;end
  else ticks<=ticks+1'b1;
 end
 always @*begin
  pulse=phase[2:0]==1||phase[2:0]==2;
  sample=pulse?8'hff:0;
  if(mode==1&&(phase==33||phase==34))sample[channel]=0;
  if(mode==2)begin
   if(phase==33||phase==34)sample[channel]=0;
   if(phase==30||phase==31)sample[channel]=1;
  end
  if(mode==3)sample[channel]=0;
  if(mode==4)sample[channel]=1;
  if(phase==0)sample=8'h10;
 end
endmodule
