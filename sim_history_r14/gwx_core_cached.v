`timescale 1ns/1ps
// Derived BTB CPU plus separate two-way I/D caches. Independent development fork.
// Backend bridges serialize each 4-word cache burst into the old word bus.
// This proves functional cache integration, NOT DDR/bus bandwidth improvement.
module gwx_core_cached #(parameter ENABLE_FORWARD=1,ENABLE_PREDICT=1,parameter ENABLE_TRAPS=1)(
 input wire clk,rst_n,
 input wire irq_external,irq_timer,irq_software,
 output wire [31:0] imem_addr,input wire [31:0] imem_rdata,
 output wire i_req_valid,input wire i_req_ready,
 input wire i_rsp_valid,output wire i_rsp_ready,input wire imem_error,
 output wire d_valid,d_write,output wire [31:0] d_addr,d_wdata,
 output wire [3:0] d_wstrb,input wire [31:0] d_rdata,input wire d_ready,d_error,
 output wire halted,output wire [3:0] trap_cause,
 output wire [31:0] debug_pc,output wire debug_flush,debug_stall,debug_forward,
 output wire trace_valid,output wire [31:0] trace_pc,trace_insn,
 output wire trace_we,output wire [4:0] trace_rd,output wire [31:0] trace_data,
 output wire [31:0] cycles,retired,branches,stalls,fetch_stalls
);
 wire [31:0] ci_addr,ci_data,cd_addr,cd_wdata,cd_rdata;
 wire ci_req,ci_req_ready,ci_rsp,ci_rsp_ready,ci_error;
 wire cd_valid,cd_write,cd_ready,cd_error;wire [3:0] cd_strb;
 gwx_core_sync #(.ENABLE_FORWARD(ENABLE_FORWARD),.ENABLE_PREDICT(ENABLE_PREDICT),.ENABLE_TRAPS(ENABLE_TRAPS)) cpu(
  .clk(clk),.rst_n(rst_n),.irq_external(irq_external),.irq_timer(irq_timer),.irq_software(irq_software),.imem_addr(ci_addr),.imem_rdata(ci_data),.imem_error(ci_error),
  .i_req_valid(ci_req),.i_req_ready(ci_req_ready),.i_rsp_valid(ci_rsp),.i_rsp_ready(ci_rsp_ready),
  .d_valid(cd_valid),.d_write(cd_write),.d_addr(cd_addr),.d_wdata(cd_wdata),.d_wstrb(cd_strb),
  .d_rdata(cd_rdata),.d_ready(cd_ready),.d_error(cd_error),
  .halted(halted),.trap_cause(trap_cause),.debug_pc(debug_pc),.debug_flush(debug_flush),
  .debug_stall(debug_stall),.debug_forward(debug_forward),
  .trace_valid(trace_valid),.trace_pc(trace_pc),.trace_insn(trace_insn),.trace_we(trace_we),.trace_rd(trace_rd),.trace_data(trace_data),
  .cycles(cycles),.retired(retired),.branches(branches),.stalls(stalls),.fetch_stalls(fetch_stalls));
 wire iv,ir,iw,irv,irr,ire,irl;
 wire [31:0] ia,id,ird;wire [3:0] is;wire [2:0] il;
 wire dv,dr,dw,drv,drr,dre,drl;
 wire [31:0] da,dd,drd;wire [3:0] ds;wire [2:0] dl;
 wire [31:0] i_hits,i_misses,d_hits,d_misses;
 gwx_cache_2way #(.SET_BITS(7)) icache(
  .clk(clk),.rst_n(rst_n),.invalidate(1'b0),.req_valid(ci_req),.req_ready(ci_req_ready),
  .req_write(1'b0),.req_cacheable(ci_addr[31:16]==16'h0000),.req_addr(ci_addr),.req_wdata(32'b0),.req_wstrb(4'b0),
  .rsp_valid(ci_rsp),.rsp_ready(ci_rsp_ready),.rsp_data(ci_data),.rsp_error(ci_error),
  .mem_req_valid(iv),.mem_req_ready(ir),.mem_req_write(iw),.mem_req_addr(ia),.mem_req_wdata(id),.mem_req_wstrb(is),.mem_req_beats(il),
  .mem_rsp_valid(irv),.mem_rsp_ready(irr),.mem_rsp_data(ird),.mem_rsp_error(ire),.mem_rsp_last(irl),.hits(i_hits),.misses(i_misses));
 // The core data interface is level-held until RESPONSE, not request acceptance.
 // Busy prevents a held store/MMIO transaction being accepted twice.
 reg data_busy;
 wire dcache_req_ready;
 wire dcache_rsp;
 assign cd_ready=dcache_rsp;
 always @(posedge clk)begin
  if(!rst_n)data_busy<=0;
  else begin
   if(cd_valid && !data_busy && dcache_req_ready)data_busy<=1;
   if(cd_valid && cd_ready)data_busy<=0;
  end
 end
 gwx_cache_2way #(.SET_BITS(6),.COMB_READ_HIT(1)) dcache(
  .clk(clk),.rst_n(rst_n),.invalidate(1'b0),.req_valid(cd_valid && !data_busy),.req_ready(dcache_req_ready),
  .req_write(cd_write),.req_cacheable(cd_addr[31:16]==16'h0000 || cd_addr[31:16]==16'h1000 || cd_addr[31:18]==14'h0c00),
  .req_addr({cd_addr[31:2],2'b0}),.req_wdata(cd_wdata),.req_wstrb(cd_strb),
  .rsp_valid(dcache_rsp),.rsp_ready(cd_valid),.rsp_data(cd_rdata),.rsp_error(cd_error),
  .mem_req_valid(dv),.mem_req_ready(dr),.mem_req_write(dw),.mem_req_addr(da),.mem_req_wdata(dd),.mem_req_wstrb(ds),.mem_req_beats(dl),
  .mem_rsp_valid(drv),.mem_rsp_ready(drr),.mem_rsp_data(drd),.mem_rsp_error(dre),.mem_rsp_last(drl),.hits(d_hits),.misses(d_misses));
 gwx_icache_word_bridge ib(
  .clk(clk),.rst_n(rst_n),.cmd_valid(iv),.cmd_ready(ir),.cmd_addr(ia),.cmd_beats(il),
  .rsp_valid(irv),.rsp_ready(irr),.rsp_data(ird),.rsp_error(ire),.rsp_last(irl),
  .word_req_valid(i_req_valid),.word_req_ready(i_req_ready),.word_addr(imem_addr),
  .word_rsp_valid(i_rsp_valid),.word_rsp_ready(i_rsp_ready),.word_rsp_data(imem_rdata),.word_rsp_error(imem_error));
 gwx_dcache_word_bridge db(
  .clk(clk),.rst_n(rst_n),.cmd_valid(dv),.cmd_ready(dr),.cmd_write(dw),.cmd_addr(da),.cmd_data(dd),.cmd_strb(ds),.cmd_beats(dl),
  .rsp_valid(drv),.rsp_ready(drr),.rsp_data(drd),.rsp_error(dre),.rsp_last(drl),
  .word_valid(d_valid),.word_write(d_write),.word_addr(d_addr),.word_wdata(d_wdata),.word_strb(d_wstrb),
  .word_rdata(d_rdata),.word_ready(d_ready),.word_error(d_error));
endmodule

// Transparent command issue and pipelined, single-outstanding read beats.
module gwx_icache_word_bridge(
 input wire clk,rst_n,input wire cmd_valid,output wire cmd_ready,
 input wire [31:0] cmd_addr,input wire [2:0] cmd_beats,
 output wire rsp_valid,input wire rsp_ready,output wire [31:0] rsp_data,output wire rsp_error,rsp_last,
 output wire word_req_valid,input wire word_req_ready,output wire [31:0] word_addr,
 input wire word_rsp_valid,output wire word_rsp_ready,input wire [31:0] word_rsp_data,input wire word_rsp_error
);
 localparam IDLE=0,ISSUE=1,WAIT=2;
 reg [1:0]state;reg[31:0]base;reg[2:0]beats,index;
 wire old_accept=state==WAIT && word_rsp_valid && rsp_ready;
 assign cmd_ready=rst_n && state==IDLE;
 assign rsp_last=index==beats-1;
 assign word_req_valid=rst_n && (state==ISSUE || (state==IDLE && cmd_valid) || (old_accept && !rsp_last));
 assign word_addr=state==IDLE?cmd_addr:base+{27'b0,(state==WAIT?index+3'd1:index),2'b0};
 assign rsp_valid=rst_n && state==WAIT && word_rsp_valid;
 assign word_rsp_ready=rst_n && state==WAIT && rsp_ready;
 assign rsp_data=word_rsp_data;assign rsp_error=word_rsp_error;
 always @(posedge clk)begin
  if(!rst_n)begin state<=IDLE;base<=0;beats<=0;index<=0;end
  else case(state)
   IDLE:if(cmd_valid)begin base<=cmd_addr;beats<=cmd_beats;index<=0;state<=word_req_ready?WAIT:ISSUE;end
   ISSUE:if(word_req_ready)state<=WAIT;
   WAIT:if(word_rsp_valid && rsp_ready)begin
    if(rsp_last)state<=IDLE;
    else begin index<=index+1'b1;state<=word_req_ready?WAIT:ISSUE;end
   end
   default:state<=IDLE;
  endcase
 end
endmodule

// The level-held backend commits only once. If its result cannot be consumed,
// capture it before dropping word_valid; never hold a committed store active.
module gwx_dcache_word_bridge(
 input wire clk,rst_n,input wire cmd_valid,output wire cmd_ready,input wire cmd_write,
 input wire [31:0] cmd_addr,cmd_data,input wire [3:0] cmd_strb,input wire [2:0] cmd_beats,
 output wire rsp_valid,input wire rsp_ready,output wire[31:0] rsp_data,output wire rsp_error,output wire rsp_last,
 output wire word_valid,word_write,output wire [31:0] word_addr,word_wdata,output wire [3:0] word_strb,
 input wire[31:0]word_rdata,input wire word_ready,word_error
);
 localparam IDLE=0,ACTIVE=1,RESP=2;
 reg[1:0]state;reg[31:0]base,data,held_data;reg writing,held_error;reg[3:0]strobes;reg[2:0]beats,index;
 assign cmd_ready=rst_n && state==IDLE;
 assign word_valid=rst_n && (state==ACTIVE || (state==IDLE && cmd_valid));
 assign word_write=state==IDLE?cmd_write:writing;
 assign word_addr=state==IDLE?cmd_addr:base+{27'b0,index,2'b0};
 assign word_wdata=state==IDLE?cmd_data:data;assign word_strb=state==IDLE?cmd_strb:strobes;
 assign rsp_valid=rst_n && (state==RESP || (state==ACTIVE && word_ready));
 assign rsp_last=index==beats-1;
 assign rsp_data=state==ACTIVE?word_rdata:held_data;
 assign rsp_error=state==ACTIVE?word_error:held_error;
 always @(posedge clk)begin
  if(!rst_n)begin state<=IDLE;base<=0;data<=0;writing<=0;strobes<=0;beats<=0;index<=0;held_data<=0;held_error<=0;end
  else case(state)
   IDLE:if(cmd_valid)begin
    base<=cmd_addr;data<=cmd_data;writing<=cmd_write;strobes<=cmd_strb;beats<=cmd_beats;index<=0;
    if(word_ready)begin held_data<=word_rdata;held_error<=word_error;state<=RESP;end
    else state<=ACTIVE;
   end
   ACTIVE:if(word_ready)begin
    if(rsp_ready)begin if(rsp_last)state<=IDLE;else index<=index+1'b1;end
    else begin held_data<=word_rdata;held_error<=word_error;state<=RESP;end
   end
   RESP:if(rsp_ready)begin if(rsp_last)state<=IDLE;else begin index<=index+1'b1;state<=ACTIVE;end end
   default:state<=IDLE;
  endcase
 end
endmodule
