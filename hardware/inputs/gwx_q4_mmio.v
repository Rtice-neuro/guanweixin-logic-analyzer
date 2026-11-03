`timescale 1ns/1ps
// Ordered commit-qualified interface. Legacy beat mode remains available.
// Buffered mode reuses one 64-byte activation across many weight rows.
module gwx_q4_mmio(
 input wire clk,rst_n,input wire[7:0]address,input wire write,
 input wire[31:0]wdata,input wire[3:0]wstrb,input wire commit,
 output reg[31:0]rdata,output reg error
);
 reg[31:0]xlo,xhi,packed_weights,completed;
 reg[31:0]xlo_bank[0:7],xhi_bank[0:7],weight_bank[0:7];
 reg[15:0]x_valid;reg[7:0]w_valid;reg buffered;reg[2:0]beat;
 reg[31:0]activation_writes,weight_writes,buffer_starts;
 wire in_ready,out_valid,out_error;wire signed[31:0]result;
 wire xreg=address>=8'h40 && address<=8'h7c && address[1:0]==0;
 wire wreg=address>=8'h80 && address<=8'h9c && address[1:0]==0;
 wire legacy_feed=commit&&write&&address==8'h0c&&!error;
 wire start=commit&&write&&address==8'ha0&&!error;
 wire consume=commit&&write&&address==8'h18&&wstrb==4'hf&&wdata==1&&out_valid&&!buffered;
 wire[31:0]packed_word=buffered?weight_bank[beat]:packed_weights;
 wire[63:0]xs=buffered?{xhi_bank[beat],xlo_bank[beat]}:{xhi,xlo};
 wire[63:0]weights;genvar lane;
 generate for(lane=0;lane<8;lane=lane+1)begin:unpack
  assign weights[lane*8+:8]={{4{packed_word[lane*4+3]}},packed_word[lane*4+:4]};
 end endgenerate
 gwx_int8_group_dot kernel(.clk(clk),.rst_n(rst_n),.in_valid(legacy_feed||buffered),.in_ready(in_ready),
 .in_x(xs),.in_w(weights),.in_keep(buffered?8'hff:wdata[15:8]),.in_last(buffered?beat==7:wdata[0]),
 .out_valid(out_valid),.out_ready(consume),.out_dot(result),.out_error(out_error));
 always @*begin
  rdata=0;error=0;
  if(address[1:0]!=0)error=1;
  else if(xreg)begin rdata=address[2]?xhi_bank[address[5:3]]:xlo_bank[address[5:3]];error=write&&(buffered||out_valid);end
  else if(wreg)begin rdata=weight_bank[address[4:2]];error=write&&(buffered||out_valid);end
  else case(address)
   8'h00:begin rdata=xlo;error=write&&buffered;end
   8'h04:begin rdata=xhi;error=write&&buffered;end
   8'h08:begin rdata=packed_weights;error=write&&buffered;end
   8'h0c:error=!write||(wdata&32'hffff00fe)!=0||!in_ready||out_valid||buffered;
   8'h10:begin rdata={29'b0,out_error,out_valid,(in_ready&&!out_valid&&!buffered)};error=write;end
   8'h14:begin rdata=result;error=write||!out_valid;end
   8'h18:error=!write||wdata!=1||!out_valid||buffered;
   8'h1c:begin rdata=32'h47575134;error=write;end
   8'h20:begin rdata=completed;error=write;end
   8'ha0:error=!write||wdata!=1||buffered||out_valid||!in_ready||x_valid!=16'hffff||w_valid!=8'hff;
   8'ha4:begin rdata=32'h00010040;error=write;end
   8'ha8:begin rdata=activation_writes;error=write;end
   8'hac:begin rdata=weight_writes;error=write;end
   8'hb0:begin rdata=buffer_starts;error=write;end
   default:error=1;
  endcase
  if(write&&wstrb!=4'hf)error=1;
 end
 integer i;
 always @(posedge clk)begin
  if(!rst_n)begin
   xlo<=0;xhi<=0;packed_weights<=0;completed<=0;x_valid<=0;w_valid<=0;buffered<=0;beat<=0;
   activation_writes<=0;weight_writes<=0;buffer_starts<=0;
   for(i=0;i<8;i=i+1)begin xlo_bank[i]<=0;xhi_bank[i]<=0;weight_bank[i]<=0;end
  end else begin
   if(buffered&&in_ready)begin if(beat==7)begin buffered<=0;beat<=0;end else beat<=beat+1'b1;end
   if(commit&&write&&!error)begin
    if(xreg)begin
     if(address[2])xhi_bank[address[5:3]]<=wdata;else xlo_bank[address[5:3]]<=wdata;
     x_valid[address[5:2]]<=1;activation_writes<=activation_writes+1'b1;
    end else if(wreg)begin weight_bank[address[4:2]]<=wdata;w_valid[address[4:2]]<=1;weight_writes<=weight_writes+1'b1;end
    else case(address)
     8'h00:xlo<=wdata;
     8'h04:xhi<=wdata;
     8'h08:packed_weights<=wdata;
     8'h0c:if(wdata[0])completed<=completed+1'b1;
     8'ha0:begin buffered<=1;beat<=0;w_valid<=0;completed<=completed+1'b1;buffer_starts<=buffer_starts+1'b1;end
    endcase
   end
  end
 end
endmodule
