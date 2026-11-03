`timescale 1ns/1ps
// Derived cache_cpu_v1: requested-word fault precision; bad fills never installed.
// Two-way set associative, 4 words/line, write-through/no-write-allocate.
// One outstanding CPU transaction; ordered burst read backend with explicit last.
// Uncacheable accesses bypass tags and use a single-beat backend transaction.
// No coherence/DMA snoop support. Invalidate only accepted while idle.
module gwx_cache_2way #(parameter SET_BITS=4, parameter FAST_READ_HIT=1, parameter COMB_READ_HIT=0)(
 input wire clk,rst_n,invalidate,
 input wire req_valid,output wire req_ready,
 input wire req_write,req_cacheable,input wire [31:0] req_addr,req_wdata,
 input wire [3:0] req_wstrb,
 output wire rsp_valid,input wire rsp_ready,
 output wire [31:0] rsp_data,output wire rsp_error,
 output wire mem_req_valid,input wire mem_req_ready,
 output wire mem_req_write,output wire [31:0] mem_req_addr,mem_req_wdata,
 output wire [3:0] mem_req_wstrb,output wire [2:0] mem_req_beats,
 input wire mem_rsp_valid,output wire mem_rsp_ready,
 input wire [31:0] mem_rsp_data,input wire mem_rsp_error,mem_rsp_last,
 output reg [31:0] hits,misses
);
 reg held_rsp_valid,held_rsp_error;reg[31:0]held_rsp_data;
 localparam SETS=1<<SET_BITS,TAG_BITS=28-SET_BITS;
 localparam IDLE=0,LOOKUP=1,SEND=2,FILL=3,WRITE_WAIT=4,RESP=5;
 reg [2:0] state;
 reg [31:0] address,write_data,critical_data;
 reg [3:0] strobes;
 reg writing,cacheable,chosen_way,write_hit,fill_bad,critical_error;
 reg [5:0] beat;
 reg valid0[0:SETS-1],valid1[0:SETS-1],lru[0:SETS-1];
 reg [TAG_BITS-1:0] tag0[0:SETS-1],tag1[0:SETS-1];
 wire [31:0] data0_q,data1_q;
 wire [SET_BITS-1:0] set_index=address[SET_BITS+3:4];
 wire [TAG_BITS-1:0] tag=address[31:SET_BITS+4];
 wire [1:0] word_index=address[3:2];
 wire hit0=valid0[set_index] && tag0[set_index]==tag;
 wire hit1=valid1[set_index] && tag1[set_index]==tag;
 wire hit=cacheable && (hit0 || hit1);
 wire [SET_BITS-1:0] incoming_set=req_addr[SET_BITS+3:4];
 wire [TAG_BITS-1:0] incoming_tag=req_addr[31:SET_BITS+4];
 wire incoming_hit0=valid0[incoming_set] && tag0[incoming_set]==incoming_tag;
 wire incoming_hit1=valid1[incoming_set] && tag1[incoming_set]==incoming_tag;
 // Read arrays are asynchronous. Register each accepted hit's data and error;
 // response backpressure cannot expose a changing request address to the CPU.
 wire incoming_read_hit=FAST_READ_HIT && !req_write && req_cacheable &&
     req_addr[1:0]==0 && (incoming_hit0 || incoming_hit1);
 wire [SET_BITS+1:0] data_index=(state==IDLE || state==RESP)?
     req_addr[SET_BITS+3:2]:{set_index,word_index};
 // Only idle hits are transparent; stalled responses are registered.
 wire immediate_hit=COMB_READ_HIT && rst_n && !invalidate && state==IDLE && req_valid && incoming_read_hit;
 assign rsp_valid=held_rsp_valid || immediate_hit;
 assign rsp_data=immediate_hit?(incoming_hit0?data0_q:data1_q):held_rsp_data;
 assign rsp_error=immediate_hit?1'b0:held_rsp_error;
 wire [SET_BITS+1:0] fill_index={set_index,beat[1:0]};

 wire fill_write=rst_n && state==FILL && mem_rsp_valid && cacheable && beat<4;
 wire hit_write=rst_n && state==WRITE_WAIT && mem_rsp_valid && write_hit && !mem_rsp_error && mem_rsp_last && !fill_bad;
 wire array_write=fill_write || hit_write;
 wire [SET_BITS+1:0] array_write_addr=fill_write?fill_index:data_index;
 wire [31:0] array_write_data=fill_write?mem_rsp_data:write_data;
 wire [3:0] array_write_strb=fill_write?4'b1111:strobes;
 gwx_cache_data_array #(.ADDR_BITS(SET_BITS+2))way0(.clk(clk),.write_en(array_write && !chosen_way),
  .write_addr(array_write_addr),.read_addr(data_index),.write_data(array_write_data),.write_strb(array_write_strb),.read_data(data0_q));
 gwx_cache_data_array #(.ADDR_BITS(SET_BITS+2))way1(.clk(clk),.write_en(array_write && chosen_way),
  .write_addr(array_write_addr),.read_addr(data_index),.write_data(array_write_data),.write_strb(array_write_strb),.read_data(data1_q));
 
 integer i,b;
 // Consume an old response and accept the next request on the same edge.
 assign req_ready=rst_n && !invalidate && (state==IDLE ||
     (FAST_READ_HIT && state==RESP && held_rsp_valid && rsp_ready));
 assign mem_req_valid=state==SEND;
 assign mem_req_write=writing;
 assign mem_req_addr=(!writing && cacheable)?{address[31:4],4'b0}:address;
 assign mem_req_wdata=write_data;
 assign mem_req_wstrb=strobes;
 assign mem_req_beats=(!writing && cacheable)?3'd4:3'd1;
 assign mem_rsp_ready=state==FILL || state==WRITE_WAIT;
 always @(posedge clk) begin
  if(!rst_n) begin
   state<=IDLE;held_rsp_valid<=0;held_rsp_data<=0;held_rsp_error<=0;
   address<=0;write_data<=0;strobes<=0;writing<=0;cacheable<=0;
   critical_data<=0;beat<=0;fill_bad<=0;chosen_way<=0;write_hit<=0;critical_error<=0;
   hits<=0;misses<=0;
   for(i=0;i<SETS;i=i+1)begin valid0[i]<=0;valid1[i]<=0;lru[i]<=0;end
  end else case(state)
   IDLE: begin
    if(invalidate)for(i=0;i<SETS;i=i+1)begin valid0[i]<=0;valid1[i]<=0;lru[i]<=0;end

   end
   LOOKUP: begin
    if(address[1:0]!=0)begin held_rsp_valid<=1;held_rsp_error<=1;held_rsp_data<=0;state<=RESP;end
    else if(writing)begin
     write_hit<=hit;chosen_way<=hit1 && !hit0;fill_bad<=0;state<=SEND;
    end else if(hit)begin
     hits<=hits+1;lru[set_index]<=hit0;
     held_rsp_data<=hit0?data0_q:data1_q;held_rsp_error<=0;held_rsp_valid<=1;state<=RESP;
    end else begin
     if(cacheable)begin
      misses<=misses+1;
      chosen_way<=!valid0[set_index]?0:(!valid1[set_index]?1:lru[set_index]);
      if(!valid0[set_index] || (valid1[set_index] && !lru[set_index]))valid0[set_index]<=0;
      else valid1[set_index]<=0;
     end
     beat<=0;fill_bad<=0;critical_data<=0;critical_error<=0;state<=SEND;
    end
   end
   SEND:if(mem_req_ready)state<=writing?WRITE_WAIT:FILL;
   FILL:if(mem_rsp_valid)begin
    if(mem_rsp_error)fill_bad<=1;
    if(cacheable && beat<4)begin
     // Writes routed through the explicit data-array port below.
     if(beat=={4'b0,word_index})begin critical_data<=mem_rsp_data;critical_error<=mem_rsp_error;end
    end
    if(mem_rsp_last)begin
     held_rsp_error<=cacheable ? ((beat!=3) || ((beat=={4'b0,word_index})?mem_rsp_error:critical_error)) : (fill_bad || mem_rsp_error || beat!=0);
     held_rsp_data<=cacheable?((beat=={4'b0,word_index})?mem_rsp_data:critical_data):mem_rsp_data;
     held_rsp_valid<=1;state<=RESP;
     if(cacheable && !fill_bad && !mem_rsp_error && beat==3)begin
      if(chosen_way)begin tag1[set_index]<=tag;valid1[set_index]<=1;end
      else begin tag0[set_index]<=tag;valid0[set_index]<=1;end
      lru[set_index]<=!chosen_way;
     end
    end else begin
     if((cacheable && beat>=3) || (!cacheable && beat>=0))fill_bad<=1;
     if(beat!=63)beat<=beat+1;
    end
   end
   WRITE_WAIT:if(mem_rsp_valid)begin
    // Drain malformed multi-beat write acknowledgements before new commands.
    if(!mem_rsp_last || mem_rsp_error)fill_bad<=1;
    if(write_hit)begin
     if(mem_rsp_error || !mem_rsp_last || fill_bad)begin
      if(chosen_way)valid1[set_index]<=0;else valid0[set_index]<=0;
     end else begin
      // Hit write updates data-array byte enables below.
      lru[set_index]<=!chosen_way;
     end
    end
    if(mem_rsp_last)begin held_rsp_valid<=1;held_rsp_error<=mem_rsp_error || fill_bad;held_rsp_data<=0;state<=RESP;end
   end
   RESP:if(rsp_ready)begin held_rsp_valid<=0;state<=IDLE;end
   default:state<=IDLE;
  endcase
  // Later nonblocking assignments own turnover; slow paths are unchanged.
  if(rst_n && req_valid && req_ready)begin
   address<=req_addr;write_data<=req_wdata;strobes<=req_wstrb;
   writing<=req_write;cacheable<=req_cacheable;state<=LOOKUP;
   // Write-through: remove tag LOOKUP wait, still wait for backend ACK.
   if(req_write && req_addr[1:0]==0)begin
    write_hit<=req_cacheable && (incoming_hit0 || incoming_hit1);
    chosen_way<=incoming_hit1 && !incoming_hit0;fill_bad<=0;state<=SEND;
   end
   if(incoming_read_hit)begin
    hits<=hits+1;lru[incoming_set]<=incoming_hit0;
    held_rsp_data<=incoming_hit0?data0_q:data1_q;
    held_rsp_error<=0;held_rsp_valid<=1;state<=RESP;
    if(COMB_READ_HIT && state==IDLE && rsp_ready)begin held_rsp_valid<=0;state<=IDLE;end
   end
  end
 end
endmodule

// One explicit write port and asynchronous read, byte lanes in separate banks.
// No reset on data: validity/tag logic owns reset/invalidation.
module gwx_cache_data_array #(parameter ADDR_BITS=6)(
 input wire clk,write_en,input wire [ADDR_BITS-1:0] write_addr,read_addr,
 input wire [31:0] write_data,input wire [3:0] write_strb,output wire [31:0] read_data
);
 genvar lane;
 generate for(lane=0;lane<4;lane=lane+1)begin:byte_bank
  reg [7:0] memory[0:(1<<ADDR_BITS)-1];
  always @(posedge clk)if(write_en && write_strb[lane])memory[write_addr]<=write_data[8*lane+:8];
  assign read_data[8*lane+:8]=memory[read_addr];
 end endgenerate
endmodule
