`timescale 1ns/1ps
// LLM building block ONLY: 64 signed INT8 products per quantization group.
// Eight products per accepted beat. Byte lane zero is bits[7:0].
// Int32 result requires software/backend multiplication by x_scale*w_scale.
// No tokenizer, attention, model weights or complete inference in this IP.
module gwx_int8_group_dot(
 input wire clk,rst_n,
 input wire in_valid,output wire in_ready,
 input wire [63:0] in_x,in_w,input wire [7:0] in_keep,input wire in_last,
 output reg out_valid,input wire out_ready,
 output reg signed [31:0] out_dot,output reg out_error
);
 reg signed [31:0] acc;
 reg [6:0] count;
 reg group_error;
 reg signed [15:0] product[0:7];
 reg signed [31:0] beat_sum;
 reg [3:0] beat_count;
 wire [7:0] new_count={1'b0,count}+beat_count;
 integer lane;
 assign in_ready=rst_n && (!out_valid || out_ready);
 always @* begin
  beat_sum=0;beat_count=0;
  for(lane=0;lane<8;lane=lane+1)begin
   product[lane]=$signed(in_x[8*lane+:8])*$signed(in_w[8*lane+:8]);
   if(in_keep[lane])begin
    beat_sum=beat_sum+{{16{product[lane][15]}},product[lane]};
    beat_count=beat_count+1'b1;
   end
  end
 end
 always @(posedge clk)begin
  if(!rst_n)begin
   acc<=0;count<=0;group_error<=0;
   out_valid<=0;out_dot<=0;out_error<=0;
  end else begin
   if(out_valid && out_ready)out_valid<=0;
   if(in_valid && in_ready)begin
    if(in_last)begin
     out_dot<=acc+beat_sum;
     out_error<=group_error || new_count!=64;
     out_valid<=1;
     acc<=0;count<=0;group_error<=0;
    end else begin
     acc<=acc+beat_sum;
     count<=new_count>127 ? 7'd127 : new_count[6:0];
     if(new_count>=64)group_error<=1;
    end
   end
  end
 end
endmodule
